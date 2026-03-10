"""
Orchestrator — Visa Application Multi-Agent System (Phase 1)

Coordinates the Intake → Research → Analysis pipeline.
Manages shared session state and agent handoffs.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI

from agents.intake_agent import IntakeAgent, ApplicantProfile
from agents.research_agent import ResearchAgent, ResearchResult
from agents.analysis_agent import AnalysisAgent, VisaReport
from agents.logger import AgentLogger


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class PipelineStage(str, Enum):
    INTAKE = "intake"
    RESEARCHING = "researching"
    ANALYSING = "analysing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class PipelineState:
    stage: PipelineStage = PipelineStage.INTAKE
    profile: Optional[ApplicantProfile] = None
    research: Optional[ResearchResult] = None
    report: Optional[VisaReport] = None
    error_message: Optional[str] = None
    chat_history: list[dict] = field(default_factory=list)  # {"role": "user"|"assistant", "content": str}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class VisaOrchestrator:
    """
    Top-level coordinator for the Phase 1 visa agent pipeline.
    Exposes a single `chat()` method for the Streamlit UI to call.
    """

    def __init__(self, openai_api_key: str, model: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.3,
            api_key=openai_api_key,
        )
        self.agent_logger = AgentLogger()
        self.intake_agent = IntakeAgent(self.llm)
        self.research_agent = ResearchAgent(self.llm, logger=self.agent_logger)
        self.analysis_agent = AnalysisAgent(self.llm, logger=self.agent_logger)
        self.state = PipelineState()

    def chat(self, user_message: str) -> tuple[str, PipelineStage]:
        """
        Process a user message and return (response_text, current_stage).
        The UI should check the stage to know when to trigger the research/analysis pipeline.
        """
        self.state.chat_history.append({"role": "user", "content": user_message})

        if self.state.stage == PipelineStage.INTAKE:
            return self._handle_intake(user_message)

        # If already complete, allow follow-up questions
        if self.state.stage == PipelineStage.COMPLETE:
            response = "Your visa requirements report is ready above. Would you like to start a new application or ask any follow-up questions?"
            self.state.chat_history.append({"role": "assistant", "content": response})
            return response, self.state.stage

        return "Processing...", self.state.stage

    def _handle_intake(self, user_message: str) -> tuple[str, PipelineStage]:
        """Delegate to the Intake Agent and trigger pipeline when profile is complete."""
        reply, is_complete = self.intake_agent.chat(user_message)

        if is_complete:
            self.state.profile = self.intake_agent.get_profile()
            # Strip the JSON block from the reply shown to the user
            display_reply = reply.split("```json")[0].strip()
            if not display_reply:
                display_reply = (
                    f"Thank you! I have all the information I need. "
                    f"Let me now research the {self.state.profile.visa_target.upper()} visa requirements for you..."
                )
            self.state.chat_history.append({"role": "assistant", "content": display_reply})
            self.state.stage = PipelineStage.RESEARCHING
            return display_reply, self.state.stage
        else:
            self.state.chat_history.append({"role": "assistant", "content": reply})
            return reply, self.state.stage

    def run_research_and_analysis(self) -> VisaReport:
        """
        Run the Research and Analysis agents synchronously.
        Called by the UI after the intake stage is complete.
        Returns the final VisaReport.
        """
        if not self.state.profile:
            raise ValueError("Cannot run research without a completed applicant profile.")

        # Stage 2: Research
        self.state.stage = PipelineStage.RESEARCHING
        self.state.research = self.research_agent.research(self.state.profile)

        # Stage 3: Analysis
        self.state.stage = PipelineStage.ANALYSING
        self.state.report = self.analysis_agent.analyse(
            self.state.research,
            schengen_main_country=self.state.profile.schengen_main_country,
        )

        self.state.stage = PipelineStage.COMPLETE
        return self.state.report

    def reset(self):
        """Reset the entire pipeline for a new application."""
        self.intake_agent.reset()
        self.agent_logger.clear()
        self.state = PipelineState()

    @property
    def stage(self) -> PipelineStage:
        return self.state.stage

    @property
    def profile(self) -> Optional[ApplicantProfile]:
        return self.state.profile

    @property
    def report(self) -> Optional[VisaReport]:
        return self.state.report

    @property
    def logs(self):
        """Return all agent log events (research + analysis)."""
        return self.agent_logger.events

    def logs_for(self, agent: str):
        """Return log events for a specific agent ('research' or 'analysis')."""
        return self.agent_logger.for_agent(agent)
