"""
Research Agent — Visa Application Multi-Agent System (Phase 1)

Takes the ApplicantProfile from the Intake Agent and retrieves
up-to-date visa requirements from the curated knowledge base.
Optionally performs a live web search to supplement the data.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import requests
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agents.intake_agent import ApplicantProfile
from agents.logger import AgentLogger


# ---------------------------------------------------------------------------
# URL verification helpers
# ---------------------------------------------------------------------------

_VERIFY_TIMEOUT = 8          # seconds per request
_VERIFY_WORKERS = 6          # parallel workers
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


def _check_url(url: str) -> tuple[str, bool, int | None, str]:
    """
    Check a single URL.  Returns (url, is_ok, status_code, reason).
    Uses HEAD first; falls back to GET if HEAD returns 405 or 403.
    Follows redirects automatically.
    """
    if not url or not url.startswith("http"):
        return url, False, None, "invalid URL"
    try:
        resp = requests.head(
            url,
            headers=_BROWSER_HEADERS,
            timeout=_VERIFY_TIMEOUT,
            allow_redirects=True,
        )
        # Some servers reject HEAD — retry with GET for a small payload
        if resp.status_code in (405, 403, 400):
            resp = requests.get(
                url,
                headers=_BROWSER_HEADERS,
                timeout=_VERIFY_TIMEOUT,
                allow_redirects=True,
                stream=True,       # don't download the body
            )
            resp.close()
        ok = resp.status_code < 400
        return url, ok, resp.status_code, "OK" if ok else f"HTTP {resp.status_code}"
    except requests.exceptions.SSLError:
        # SSL issues — try without verification as a last resort
        try:
            resp = requests.head(
                url,
                headers=_BROWSER_HEADERS,
                timeout=_VERIFY_TIMEOUT,
                allow_redirects=True,
                verify=False,
            )
            ok = resp.status_code < 400
            return url, ok, resp.status_code, "SSL warning (accessible)"
        except Exception as e:
            return url, False, None, f"SSL error: {str(e)[:60]}"
    except requests.exceptions.ConnectionError as e:
        return url, False, None, f"connection error: {str(e)[:60]}"
    except requests.exceptions.Timeout:
        return url, False, None, "timed out"
    except Exception as e:
        return url, False, None, f"error: {str(e)[:60]}"


def verify_sources(
    sources: list[dict],
    logger: Optional["AgentLogger"] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Verify all source URLs in parallel.
    Returns (verified_sources, broken_sources).
    verified_sources — accessible links (status < 400)
    broken_sources   — inaccessible links with reason attached
    """
    if not sources:
        return [], []

    if logger:
        logger._emit("research", "step", "🔎",
                     f"Verifying {len(sources)} source link(s)…")

    results: dict[str, tuple[bool, int | None, str]] = {}
    with ThreadPoolExecutor(max_workers=_VERIFY_WORKERS) as pool:
        futures = {pool.submit(_check_url, s["url"]): s for s in sources if s.get("url")}
        for future in as_completed(futures):
            url, ok, code, reason = future.result()
            results[url] = (ok, code, reason)

    verified, broken = [], []
    for src in sources:
        url = src.get("url", "")
        if not url:
            continue
        ok, code, reason = results.get(url, (False, None, "not checked"))
        if ok:
            verified.append({**src, "_status": code})
        else:
            broken.append({**src, "_reason": reason})

    if logger:
        if verified:
            logger._emit(
                "research", "success", "✅",
                f"{len(verified)} source(s) verified and accessible",
                detail="\n".join(f"• {s['title']} — {s['url']}" for s in verified),
            )
        if broken:
            logger._emit(
                "research", "warning", "⚠️",
                f"{len(broken)} source(s) could not be reached and were removed",
                detail="\n".join(
                    f"• {s['title']} ({s['_reason']}) — {s['url']}" for s in broken
                ),
            )

    return verified, broken


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ResearchResult:
    """Raw research output passed to the Analysis Agent."""
    visa_target: str                    # "uk" or "schengen"
    visa_type: str                      # Human-readable visa type name
    applicant_nationality: str
    country_of_residence: str
    destination_country: str
    purpose_of_visit: str
    raw_requirements: dict              # Full requirements dict from knowledge base
    supplementary_notes: list[str] = field(default_factory=list)  # LLM-generated additions
    sources: list[dict] = field(default_factory=list)             # URLs and titles


# ---------------------------------------------------------------------------
# Knowledge base loader
# ---------------------------------------------------------------------------

def _load_knowledge_base() -> dict:
    kb_path = Path(__file__).parent.parent / "data" / "visa_requirements.json"
    with open(kb_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Research Agent
# ---------------------------------------------------------------------------

RESEARCH_SYSTEM_PROMPT = """You are a specialist visa research assistant with deep knowledge of UK and Schengen visa requirements.

You will be given an applicant profile and a base set of visa requirements from an official knowledge base.
Your job is to:
1. Identify any special considerations specific to the applicant's nationality and country of residence
2. Note any additional documents that may be required for their specific situation
3. Flag any potential issues or red flags in their profile (e.g. prior refusals, short travel history)
4. Provide 2–3 practical tips specific to their situation

Be factual, precise, and cite the basis for any additional requirements you mention.
Format your response as a JSON object with these keys:
- "nationality_specific_notes": list of strings (requirements specific to their nationality)
- "residence_specific_notes": list of strings (requirements specific to their country of residence)  
- "situation_flags": list of strings (potential concerns or things to be aware of)
- "practical_tips": list of strings (actionable advice)
- "recommended_sources": list of {{"title": str, "url": str}} objects
"""


class ResearchAgent:
    """Retrieves and enriches visa requirements for the given applicant profile."""

    def __init__(self, llm: ChatOpenAI, logger: Optional[AgentLogger] = None):
        self.llm = llm
        self.kb = _load_knowledge_base()
        self.logger = logger or AgentLogger()

    def research(self, profile: ApplicantProfile) -> ResearchResult:
        """
        Main entry point. Returns a ResearchResult with all requirements
        and supplementary notes for the given applicant profile.
        """
        self.logger.research_start(profile.visa_target, profile.nationality, profile.destination_country)

        # 1. Pull base requirements from knowledge base
        base_reqs = self._get_base_requirements(profile)

        # 2. Use LLM to add nationality/situation-specific context
        supplementary = self._get_supplementary_context(profile, base_reqs)

        # 3. Build sources list
        sources = self._build_sources(profile, base_reqs)

        # 4. Verify all source URLs are accessible
        verified_sources, broken_sources = verify_sources(sources, logger=self.logger)

        # Store broken sources for optional display but only pass verified ones forward
        self._broken_sources = broken_sources

        self.logger.research_sources(verified_sources)
        self.logger.research_done(base_reqs.get("visa_type", ""))

        return ResearchResult(
            visa_target=profile.visa_target,
            visa_type=base_reqs.get("visa_type", ""),
            applicant_nationality=profile.nationality,
            country_of_residence=profile.country_of_residence,
            destination_country=profile.destination_country,
            purpose_of_visit=profile.purpose_of_visit,
            raw_requirements=base_reqs,
            supplementary_notes=supplementary,
            sources=verified_sources,   # only verified links
        )

    def _get_base_requirements(self, profile: ApplicantProfile) -> dict:
        """Retrieve the correct requirements block from the knowledge base."""
        if profile.visa_target == "uk":
            reqs = self.kb["uk"]["standard_visitor"]
        elif profile.visa_target == "schengen":
            reqs = self.kb["schengen"]["short_stay_c"]
        else:
            raise ValueError(f"Unsupported visa target: {profile.visa_target}")

        # Log key fields from the knowledge base
        doc_count = len(reqs.get("required_documents", []))
        self.logger.research_kb_loaded(reqs.get("visa_type", ""), doc_count)

        # Log a few key KB fields for transparency
        if profile.visa_target == "uk":
            self.logger.research_kb_entry("Fee", f"£{reqs.get('fee_gbp', 'N/A')}")
            self.logger.research_kb_entry("Processing time", reqs.get("processing_days", "N/A"))
            self.logger.research_kb_entry("Max stay", f"{reqs.get('max_stay_days', '?')} days")
            self.logger.research_kb_entry("Apply URL", reqs.get("apply_url", "N/A"))
        else:
            self.logger.research_kb_entry("Fee", f"€{reqs.get('fee_eur', 'N/A')} per adult")
            self.logger.research_kb_entry("Processing time", reqs.get("processing_days", "N/A"))
            self.logger.research_kb_entry("Max stay", f"{reqs.get('max_stay_days', '?')} days")
            self.logger.research_kb_entry("Apply URL", reqs.get("apply_url", "N/A"))
            self.logger.research_kb_entry(
                "Schengen member states",
                ", ".join(reqs.get("member_states", [])[:10]) + "…"
            )

        # Log document list
        docs = reqs.get("required_documents", [])
        mandatory = [d["document"] for d in docs if d.get("mandatory")]
        optional  = [d["document"] for d in docs if not d.get("mandatory")]
        if mandatory:
            self.logger.research_kb_entry(
                f"Mandatory documents ({len(mandatory)})",
                "\n".join(f"• {d}" for d in mandatory)
            )
        if optional:
            self.logger.research_kb_entry(
                f"Recommended documents ({len(optional)})",
                "\n".join(f"• {d}" for d in optional)
            )

        return reqs

    def _get_supplementary_context(self, profile: ApplicantProfile, base_reqs: dict) -> list[str]:
        """Use LLM to generate nationality/situation-specific supplementary notes."""
        self.logger.research_llm_start(profile.nationality, profile.country_of_residence)

        prompt = f"""Applicant Profile:
- Nationality: {profile.nationality}
- Country of Residence: {profile.country_of_residence}
- Destination: {profile.destination_country}
- Purpose: {profile.purpose_of_visit}
- Employment Status: {profile.employment_status or 'Not specified'}
- Previous UK Visa: {profile.has_previous_uk_visa}
- Previous Schengen Visa: {profile.has_previous_schengen_visa}
- Previous Refusal: {profile.has_previous_refusal}
- Visa Type: {base_reqs.get('visa_type', '')}

Base requirements are already covered. Please provide nationality and situation-specific supplementary research."""

        messages = [
            SystemMessage(content=RESEARCH_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = self.llm.invoke(messages)
        content = response.content

        # Parse JSON from response
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            data = json.loads(json_str)

            notes = []
            section_map = {
                "nationality_specific_notes": "Nationality-Specific Notes",
                "residence_specific_notes":   "Residence-Specific Notes",
                "situation_flags":            "Situation Flags",
                "practical_tips":             "Practical Tips",
            }
            for key, label in section_map.items():
                items = data.get(key, [])
                if items:
                    self.logger.research_notes_section(label, items)
                    notes.append(f"**{label}:**")
                    notes.extend([f"• {item}" for item in items])

            # Add recommended sources
            for src in data.get("recommended_sources", []):
                self._extra_sources = getattr(self, "_extra_sources", [])
                self._extra_sources.append(src)

            self.logger.research_llm_done(len(notes), len(getattr(self, "_extra_sources", [])))
            return notes

        except (json.JSONDecodeError, KeyError):
            self.logger.error("research", "Failed to parse LLM JSON response — using raw text", detail=content[:300])
            return [content]

    def _build_sources(self, profile: ApplicantProfile, base_reqs: dict) -> list[dict]:
        """Build the list of official source links."""
        sources = [
            {"title": f"Official {base_reqs.get('visa_type', 'Visa')} Information", "url": base_reqs.get("info_url", "")},
            {"title": "Apply Online", "url": base_reqs.get("apply_url", "")},
        ]

        # Add VAC provider links
        for provider, url in base_reqs.get("vac_providers", {}).items():
            sources.append({"title": f"Visa Application Centre — {provider}", "url": url})

        # Add country-specific links for Schengen
        if profile.visa_target == "schengen" and profile.schengen_main_country:
            country_links = base_reqs.get("country_specific_links", {})
            for country, url in country_links.items():
                if country.lower() in profile.schengen_main_country.lower():
                    sources.append({"title": f"{country} Embassy Visa Portal", "url": url})

        # Add any extra sources found during LLM research
        extra = getattr(self, "_extra_sources", [])
        sources.extend(extra)

        return [s for s in sources if s.get("url")]
