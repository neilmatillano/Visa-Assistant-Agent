"""
Analysis Agent — Visa Application Multi-Agent System (Phase 2)

Takes the ResearchResult from the Research Agent and synthesises it into
a structured, user-friendly visa requirements report with a document
checklist, step-by-step instructions, direct application links, form
download links, upload portal info, and appointment portal details.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agents.research_agent import ResearchResult
from agents.logger import AgentLogger


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DocumentItem:
    id: int
    document: str
    details: str
    mandatory: bool
    status: str = "pending"       # pending | ready | not_applicable
    upload_format: str = "PDF"
    max_file_mb: int = 2


@dataclass
class FormLink:
    """A downloadable or linkable visa application form."""
    id: str
    title: str
    description: str
    url: str
    format: str
    mandatory: bool
    notes: str = ""


@dataclass
class UploadPortal:
    """The document upload portal for this visa application."""
    name: str
    url: str
    login_url: str
    accepted_formats: list[str]
    max_file_mb: int
    notes: str
    upload_timing: str
    login_instructions: list[str] = field(default_factory=list)


@dataclass
class AppointmentPortal:
    """Appointment booking portal details."""
    name: str
    url: str
    booking_url: str
    avg_wait_weeks: int
    notes: str
    booking_steps: list[str] = field(default_factory=list)
    locations_info_url: str = ""


@dataclass
class VisaReport:
    """Final structured report delivered to the user."""
    # Header
    visa_type: str
    applicant_nationality: str
    country_of_residence: str
    destination_country: str
    purpose_of_visit: str
    schengen_main_country: Optional[str]

    # Visa details
    fee: str
    processing_time: str
    max_stay: str
    apply_url: str

    # Checklist
    mandatory_documents: list[DocumentItem]
    optional_documents: list[DocumentItem]

    # Steps
    application_steps: list[str]

    # Notes and tips
    key_notes: list[str]
    supplementary_notes: list[str]

    # Sources
    sources: list[dict]

    # Embassy selection (Schengen only)
    embassy_guidance: Optional[str] = None

    # ETA eligibility (UK only)
    eta_eligible: bool = False
    eta_note: Optional[str] = None

    # Summary narrative
    executive_summary: str = ""

    # Phase 2 additions
    forms: list[FormLink] = field(default_factory=list)
    upload_portal: Optional[UploadPortal] = None
    appointment_portals: list[AppointmentPortal] = field(default_factory=list)
    tracking_url: str = ""
    tracking_instructions: str = ""


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _load_forms(visa_target: str, schengen_country: Optional[str] = None) -> list[FormLink]:
    path = os.path.join(_DATA_DIR, "visa_forms.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        target_data = data.get(visa_target, {})
        forms_raw = list(target_data.get("forms", []))
        return [
            FormLink(
                id=fm["id"],
                title=fm["title"],
                description=fm["description"],
                url=fm["url"],
                format=fm["format"],
                mandatory=fm.get("mandatory", False),
                notes=fm.get("notes", ""),
            )
            for fm in forms_raw
        ]
    except Exception:
        return []


def _load_upload_portal(visa_target: str) -> Optional[UploadPortal]:
    path = os.path.join(_DATA_DIR, "visa_portals.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        p = data.get(visa_target, {}).get("upload_portal", {})
        if not p:
            return None
        return UploadPortal(
            name=p["name"],
            url=p["url"],
            login_url=p.get("login_url", p["url"]),
            accepted_formats=p.get("accepted_formats", ["PDF"]),
            max_file_mb=p.get("max_file_mb", 2),
            notes=p.get("notes", ""),
            upload_timing=p.get("upload_timing", "Before appointment"),
            login_instructions=p.get("login_instructions", []),
        )
    except Exception:
        return None


def _load_appointment_portals(
    visa_target: str,
    schengen_country: Optional[str] = None,
) -> tuple[list[AppointmentPortal], str, str]:
    path = os.path.join(_DATA_DIR, "visa_portals.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        target = data.get(visa_target, {})
        tracking_url = target.get("tracking_url", "")
        tracking_instructions = target.get("tracking_instructions", "")
        booking_steps = target.get("booking_steps", [])

        if visa_target == "schengen" and schengen_country:
            country_key = schengen_country.lower()
            cp = target.get("country_portals", {}).get(country_key)
            if cp:
                tracking_url = cp.get("tracking_url", tracking_url)
                portals = [AppointmentPortal(
                    name=cp["portal_name"],
                    url=cp["portal_url"],
                    booking_url=cp["booking_url"],
                    avg_wait_weeks=cp.get("avg_wait_weeks", 3),
                    notes=f"Official portal for {schengen_country} visa applications.",
                    booking_steps=booking_steps,
                    locations_info_url=cp.get("locations_info_url", cp["portal_url"]),
                )]
                return portals, tracking_url, tracking_instructions

        portals_raw = target.get("appointment_portals", [])
        portals = [
            AppointmentPortal(
                name=p["name"],
                url=p["url"],
                booking_url=p["booking_url"],
                avg_wait_weeks=p.get("avg_wait_weeks", 3),
                notes=p.get("notes", ""),
                booking_steps=booking_steps,
                locations_info_url=p.get("locations_info_url", p["url"]),
            )
            for p in portals_raw
        ]
        return portals, tracking_url, tracking_instructions
    except Exception:
        return [], "", ""


# ---------------------------------------------------------------------------
# Analysis Agent
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """You are a senior visa consultant producing a clear, actionable visa requirements report.

Given a research result, produce a concise executive summary (3–4 sentences) that:
1. States the visa type and destination
2. Summarises the key requirements and fees
3. Highlights any important considerations for this specific applicant
4. Ends with a reassuring, professional tone

Also determine:
- Whether the applicant needs to apply at a specific embassy (for Schengen, based on their itinerary)
- Any ETA eligibility (for UK, based on nationality)
- Any special flags that should be prominently displayed

Respond in JSON format:
{
  "executive_summary": "...",
  "embassy_guidance": "...",
  "eta_eligible": false,
  "eta_note": "...",
  "priority_flags": ["...", "..."]
}"""


class AnalysisAgent:
    """Synthesises research into a structured, user-friendly visa report."""

    def __init__(self, llm: ChatOpenAI, logger: Optional[AgentLogger] = None):
        self.llm = llm
        self.logger = logger or AgentLogger()

    def analyse(self, research: ResearchResult, schengen_main_country: Optional[str] = None) -> VisaReport:
        reqs = research.raw_requirements
        self.logger.analysis_start(research.visa_type, research.applicant_nationality)

        mandatory_docs = []
        optional_docs  = []
        for doc in reqs.get("required_documents", []):
            item = DocumentItem(
                id=doc["id"],
                document=doc["document"],
                details=doc["details"],
                mandatory=doc["mandatory"],
            )
            if doc["mandatory"]:
                mandatory_docs.append(item)
            else:
                optional_docs.append(item)

        self.logger.analysis_docs_parsed(len(mandatory_docs), len(optional_docs))

        if mandatory_docs:
            self.logger.events.append(__import__("agents.logger", fromlist=["LogEvent"]).LogEvent(
                ts=__import__("time").time(),
                agent="analysis",
                level="info",
                icon="📄",
                message=f"Mandatory documents checklist ({len(mandatory_docs)} items)",
                detail="\n".join(f"• {d.document}" for d in mandatory_docs),
            ))

        if research.visa_target == "uk":
            fee = f"£{reqs.get('fee_gbp', 'N/A')} (standard processing)"
        else:
            fee = f"€{reqs.get('fee_eur', 'N/A')} per adult (children 6–12: €{reqs.get('fee_eur_children_6_12', 'N/A')}, under 6: free)"

        self.logger.analysis_fee(fee)

        eta_eligible = False
        eta_note = None
        if research.visa_target == "uk":
            etas_list = reqs.get("etas_eligible", [])
            nationality_lower = research.applicant_nationality.lower()
            for country in etas_list:
                if country.lower() in nationality_lower or nationality_lower in country.lower():
                    eta_eligible = True
                    eta_note = (
                        f"As a {research.applicant_nationality} national, you may be eligible for the "
                        f"UK Electronic Travel Authorisation (ETA) instead of a full visa. "
                        f"The ETA costs £10 and is linked to your passport. "
                        f"Check eligibility at: https://www.gov.uk/guidance/apply-for-an-electronic-travel-authorisation-eta"
                    )
                    break

        self.logger.analysis_eta_check(research.applicant_nationality, eta_eligible, eta_note)

        steps = reqs.get("application_steps", [])
        self.logger.analysis_steps(len(steps))
        if steps:
            from agents.logger import LogEvent
            import time as _time
            self.logger.events.append(LogEvent(
                ts=_time.time(),
                agent="analysis",
                level="info",
                icon="📋",
                message=f"Application steps ({len(steps)} steps)",
                detail="\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)),
            ))

        self.logger.analysis_llm_start()
        llm_output = self._get_llm_analysis(research, schengen_main_country, eta_eligible)

        embassy = llm_output.get("embassy_guidance")
        flags   = llm_output.get("priority_flags", [])
        self.logger.analysis_llm_done(has_embassy=bool(embassy), has_flags=len(flags))

        if embassy:
            self.logger.analysis_embassy(embassy)
        if flags:
            self.logger.analysis_flags(flags)

        # Phase 2: load forms and portal data
        forms = _load_forms(research.visa_target, schengen_main_country)
        upload_portal = _load_upload_portal(research.visa_target)
        appointment_portals, tracking_url, tracking_instructions = _load_appointment_portals(
            research.visa_target, schengen_main_country
        )

        self.logger.analysis_done(reqs.get("visa_type", ""), research.destination_country)

        return VisaReport(
            visa_type=reqs.get("visa_type", ""),
            applicant_nationality=research.applicant_nationality,
            country_of_residence=research.country_of_residence,
            destination_country=research.destination_country,
            purpose_of_visit=research.purpose_of_visit,
            schengen_main_country=schengen_main_country,
            fee=fee,
            processing_time=reqs.get("processing_days", ""),
            max_stay=f"Up to {reqs.get('max_stay_days', '?')} days",
            apply_url=reqs.get("apply_url", ""),
            mandatory_documents=mandatory_docs,
            optional_documents=optional_docs,
            application_steps=steps,
            key_notes=reqs.get("key_notes", []),
            supplementary_notes=research.supplementary_notes,
            sources=research.sources,
            embassy_guidance=embassy,
            eta_eligible=eta_eligible,
            eta_note=eta_note,
            executive_summary=llm_output.get("executive_summary", ""),
            forms=forms,
            upload_portal=upload_portal,
            appointment_portals=appointment_portals,
            tracking_url=tracking_url,
            tracking_instructions=tracking_instructions,
        )

    def _get_llm_analysis(
        self,
        research: ResearchResult,
        schengen_main_country: Optional[str],
        eta_eligible: bool,
    ) -> dict:
        context = f"""
Visa Type: {research.visa_type}
Applicant Nationality: {research.applicant_nationality}
Country of Residence: {research.country_of_residence}
Destination: {research.destination_country}
Purpose: {research.purpose_of_visit}
Schengen Main Country: {schengen_main_country or 'N/A'}
ETA Eligible: {eta_eligible}
Supplementary Research Notes:
{chr(10).join(research.supplementary_notes[:10]) if research.supplementary_notes else 'None'}
"""
        messages = [
            SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ]
        response = self.llm.invoke(messages)
        content = response.content

        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, KeyError):
            self.logger.error("analysis", "Failed to parse LLM JSON — using fallback", detail=content[:300])
            return {
                "executive_summary": content[:500],
                "embassy_guidance": None,
                "eta_eligible": eta_eligible,
                "eta_note": None,
                "priority_flags": [],
            }
