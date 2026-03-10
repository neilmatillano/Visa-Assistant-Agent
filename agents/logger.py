"""
logger.py — Structured activity logger for the Visa Agent pipeline.

Each agent receives a shared AgentLogger instance and emits typed log events
as it works. The Streamlit UI reads these events from st.session_state to
render a live activity feed.

Log event structure:
    {
        "ts":      float,        # time.time() timestamp
        "agent":   str,          # "research" | "analysis"
        "level":   str,          # "info" | "success" | "warning" | "error" | "step"
        "icon":    str,          # emoji for display
        "message": str,          # human-readable log line
        "detail":  str | None,   # optional extra detail (collapsed by default)
    }
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Log event
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LogEvent:
    ts:      float
    agent:   str
    level:   str          # info | success | warning | error | step
    icon:    str
    message: str
    detail:  Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────

class AgentLogger:
    """
    Lightweight in-memory logger shared across agents in a single pipeline run.
    Thread-safe enough for Streamlit's single-threaded execution model.
    """

    def __init__(self):
        self.events: list[LogEvent] = []

    def _emit(self, agent: str, level: str, icon: str, message: str, detail: Optional[str] = None):
        self.events.append(LogEvent(
            ts=time.time(),
            agent=agent,
            level=level,
            icon=icon,
            message=message,
            detail=detail,
        ))

    # ── Research agent helpers ────────────────────────────────────────────────

    def research_start(self, visa_target: str, nationality: str, destination: str):
        self._emit("research", "step", "🔍",
                   f"Starting research for {nationality} national → {destination} ({visa_target.upper()} visa)")

    def research_kb_loaded(self, visa_type: str, doc_count: int):
        self._emit("research", "success", "📚",
                   f"Knowledge base loaded — {visa_type}",
                   detail=f"{doc_count} document requirements found in local knowledge base.")

    def research_kb_entry(self, key: str, value: str):
        self._emit("research", "info", "📋",
                   f"KB field: {key}",
                   detail=value)

    def research_llm_start(self, nationality: str, residence: str):
        self._emit("research", "step", "🤖",
                   f"Calling LLM for nationality-specific context ({nationality} / residing in {residence})")

    def research_llm_done(self, note_count: int, source_count: int):
        self._emit("research", "success", "✅",
                   f"LLM research complete — {note_count} supplementary notes, {source_count} sources added")

    def research_notes_section(self, section: str, items: list[str]):
        if items:
            self._emit("research", "info", "📝",
                       f"{section} ({len(items)} items)",
                       detail="\n".join(f"• {i}" for i in items))

    def research_sources(self, sources: list[dict]):
        if sources:
            lines = "\n".join(f"• {s.get('title','?')} — {s.get('url','')}" for s in sources)
            self._emit("research", "info", "🔗",
                       f"{len(sources)} official source(s) identified",
                       detail=lines)

    def research_done(self, visa_type: str):
        self._emit("research", "success", "🏁",
                   f"Research complete — {visa_type} requirements ready for analysis")

    # ── Analysis agent helpers ────────────────────────────────────────────────

    def analysis_start(self, visa_type: str, nationality: str):
        self._emit("analysis", "step", "📊",
                   f"Starting analysis — {visa_type} for {nationality} national")

    def analysis_docs_parsed(self, mandatory: int, optional: int):
        self._emit("analysis", "success", "📄",
                   f"Document checklist built — {mandatory} mandatory, {optional} recommended",
                   detail=f"Mandatory: {mandatory} documents required\nRecommended: {optional} supporting documents")

    def analysis_fee(self, fee: str):
        self._emit("analysis", "info", "💰", f"Visa fee determined: {fee}")

    def analysis_eta_check(self, nationality: str, eligible: bool, note: Optional[str] = None):
        if eligible:
            self._emit("analysis", "warning", "⚡",
                       f"ETA eligibility detected for {nationality}",
                       detail=note)
        else:
            self._emit("analysis", "info", "🛂",
                       f"Full visa required for {nationality} — ETA not applicable")

    def analysis_llm_start(self):
        self._emit("analysis", "step", "🤖",
                   "Calling LLM to generate executive summary and embassy guidance")

    def analysis_llm_done(self, has_embassy: bool, has_flags: int):
        detail_parts = []
        if has_embassy:
            detail_parts.append("Embassy selection guidance generated")
        if has_flags:
            detail_parts.append(f"{has_flags} priority flag(s) identified")
        self._emit("analysis", "success", "✅",
                   "LLM analysis complete",
                   detail="\n".join(detail_parts) if detail_parts else None)

    def analysis_embassy(self, guidance: str):
        self._emit("analysis", "info", "🏛️",
                   "Embassy selection guidance",
                   detail=guidance)

    def analysis_flags(self, flags: list[str]):
        if flags:
            self._emit("analysis", "warning", "⚠️",
                       f"{len(flags)} priority flag(s) for this applicant",
                       detail="\n".join(f"• {f}" for f in flags))

    def analysis_steps(self, count: int):
        self._emit("analysis", "info", "📋",
                   f"Application process: {count} step(s) mapped")

    def analysis_done(self, visa_type: str, dest: str):
        self._emit("analysis", "success", "🏁",
                   f"Report complete — {visa_type} requirements for {dest} ready")

    # ── Generic helpers ───────────────────────────────────────────────────────

    def error(self, agent: str, message: str, detail: Optional[str] = None):
        self._emit(agent, "error", "❌", message, detail=detail)

    def clear(self):
        self.events.clear()

    def for_agent(self, agent: str) -> list[LogEvent]:
        """Return only events for a specific agent."""
        return [e for e in self.events if e.agent == agent]
