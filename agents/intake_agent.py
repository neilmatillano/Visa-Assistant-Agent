"""
Intake Agent — Visa Application Multi-Agent System (Phase 1)

Conducts a structured conversational interview to collect all information
needed to determine the correct visa type and requirements.
Outputs a validated ApplicantProfile object.
"""

from __future__ import annotations

import json
from typing import Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class ApplicantProfile(BaseModel):
    """Structured applicant profile produced by the Intake Agent."""
    nationality: str = Field(description="Applicant's passport nationality (e.g. Filipino, Indian)")
    country_of_residence: str = Field(description="Country where applicant currently lives and will apply from")
    destination_country: str = Field(description="Country the applicant wants to visit")
    destination_city: Optional[str] = Field(default=None, description="Specific city or cities to visit")
    purpose_of_visit: str = Field(description="Reason for travel: Tourism, Business, Visiting family/friends, Study, Medical")
    travel_start_date: Optional[str] = Field(default=None, description="Intended departure date (YYYY-MM-DD or descriptive)")
    travel_end_date: Optional[str] = Field(default=None, description="Intended return date (YYYY-MM-DD or descriptive)")
    duration_days: Optional[int] = Field(default=None, description="Approximate number of days of stay")
    num_travellers: int = Field(default=1, description="Number of people travelling (including applicant)")
    has_previous_uk_visa: Optional[bool] = Field(default=None, description="Has the applicant held a UK visa before?")
    has_previous_schengen_visa: Optional[bool] = Field(default=None, description="Has the applicant held a Schengen visa before?")
    has_previous_refusal: Optional[bool] = Field(default=None, description="Has the applicant ever been refused a visa?")
    employment_status: Optional[str] = Field(default=None, description="Employed, Self-employed, Student, Retired, Unemployed")
    visa_target: str = Field(description="Determined visa target: 'uk' or 'schengen'")
    schengen_main_country: Optional[str] = Field(default=None, description="Main Schengen country to visit (for embassy selection)")


# ---------------------------------------------------------------------------
# Intake Agent
# ---------------------------------------------------------------------------

INTAKE_SYSTEM_PROMPT = """You are a friendly and professional visa application assistant specialising in UK and Schengen visas.

Your job is to conduct a conversational interview to collect the following information from the user:
1. Their nationality (passport country)
2. Their country of residence (where they currently live and will apply from)
3. Their destination country (where they want to travel)
4. The purpose of their visit (Tourism, Business, Visiting family/friends, Study, Medical)
5. Approximate travel dates or duration
6. Number of travellers
7. Whether they have held a UK or Schengen visa before
8. Whether they have ever been refused a visa
9. Their employment status

IMPORTANT RULES:
- Ask questions one or two at a time — do NOT dump all questions at once
- Be warm, conversational, and reassuring
- If the destination is a Schengen country, ask which specific country they plan to spend the most time in
- Once you have enough information, output a JSON block with the key "profile_complete": true and the full profile
- Only output the JSON when you are confident you have all required fields
- The JSON must be wrapped in ```json ... ``` code fences
- The "visa_target" field must be either "uk" or "schengen"
- If the destination is not UK or a Schengen country, politely explain that Phase 1 only supports UK and Schengen visas

Schengen countries: Austria, Belgium, Czech Republic, Denmark, Estonia, Finland, France, Germany, Greece, Hungary, Iceland, Italy, Latvia, Liechtenstein, Lithuania, Luxembourg, Malta, Netherlands, Norway, Poland, Portugal, Slovakia, Slovenia, Spain, Sweden, Switzerland.

RESIDENCE-BASED EXEMPTIONS — check these as soon as you know both the country of residence and the destination:
- If the applicant currently lives in a Schengen country (listed above) AND their destination is also a Schengen country: they do NOT need a visa. Third-country nationals with a valid Schengen residence permit can travel freely within the Schengen area. Inform them warmly, then output this JSON immediately:
  ```json
  {"no_visa_required": true, "reason": "schengen_resident", "residence": "<their country>", "destination": "<destination country>", "message": "As a resident of <country>, you can travel to <destination> with your valid residence permit and passport — no separate Schengen visa is needed."}
  ```
- If the applicant currently lives in the United Kingdom AND their destination is the United Kingdom: clarify their actual travel destination (they are already in the UK).
- UK residency does NOT exempt a non-EEA national from needing a Schengen visa. Schengen residency does NOT exempt anyone from needing a UK visa. In both those cases, continue the normal intake interview.

Begin by greeting the user and asking for their nationality and destination."""


class IntakeAgent:
    """Conversational agent that collects applicant information."""

    def __init__(self, llm: ChatOpenAI):
        self.llm = llm
        self.messages: list = [SystemMessage(content=INTAKE_SYSTEM_PROMPT)]
        self.profile: Optional[ApplicantProfile] = None
        self.is_complete = False
        self.no_visa_required = False
        self.no_visa_reason: Optional[dict] = None

    def chat(self, user_input: str) -> tuple[str, bool]:
        """
        Process a user message and return (agent_response, is_profile_complete).
        When is_profile_complete is True, self.profile is populated.
        """
        self.messages.append(HumanMessage(content=user_input))
        response = self.llm.invoke(self.messages)
        reply = response.content
        self.messages.append(AIMessage(content=reply))

        # Check if the agent has produced a complete profile JSON or a no-visa exemption
        if "```json" in reply:
            try:
                json_str = reply.split("```json")[1].split("```")[0].strip()
                data = json.loads(json_str)
                if data.get("profile_complete"):
                    self.profile = ApplicantProfile(**{
                        k: v for k, v in data.items() if k != "profile_complete"
                    })
                    self.is_complete = True
                elif data.get("no_visa_required"):
                    self.no_visa_required = True
                    self.no_visa_reason = data
                    self.is_complete = True
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # Profile parsing failed; continue conversation

        return reply, self.is_complete

    def get_profile(self) -> Optional[ApplicantProfile]:
        return self.profile

    def reset(self):
        self.messages = [SystemMessage(content=INTAKE_SYSTEM_PROMPT)]
        self.profile = None
        self.is_complete = False
        self.no_visa_required = False
        self.no_visa_reason = None
