# Visa Application Multi-Agent System — Phase 1

A multi-agent AI system that guides users through UK and Schengen visa requirements using three specialised agents: **Intake Agent**, **Research Agent**, and **Analysis Agent**.

Delivered in two formats:
- **Python + Streamlit** — interactive web application
- **n8n** — importable no-code workflow

---

## Architecture

```
User (Chat UI)
      │
      ▼
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│  INTAKE     │───▶│  RESEARCH    │───▶│  ANALYSIS    │
│  AGENT      │    │  AGENT       │    │  AGENT       │
│             │    │              │    │              │
│ Conversatio-│    │ Loads visa   │    │ Synthesises  │
│ nal intake  │    │ requirements │    │ personalised │
│ → Applicant │    │ + LLM suppl- │    │ report with  │
│   Profile   │    │   ementary   │    │ checklist,   │
│             │    │   research   │    │ steps, links │
└─────────────┘    └──────────────┘    └──────────────┘
```

**Supported Visas:**
- 🇬🇧 UK Standard Visitor Visa
- 🇪🇺 Schengen Short-Stay Visa (Type C) — all 26 Schengen countries

---

## Python + Streamlit Setup

### Prerequisites
- Python 3.9+
- OpenAI API key

### Installation

```bash
cd visa_agent
pip install langchain langchain-openai openai streamlit python-dotenv pydantic
```

### Running the App

```bash
streamlit run app.py
```

Then open http://localhost:8501 in your browser.

Enter your OpenAI API key in the sidebar and start chatting with the Intake Agent.

### Project Structure

```
visa_agent/
├── app.py                          # Streamlit application
├── agents/
│   ├── __init__.py
│   ├── intake_agent.py             # Agent 1: Conversational intake
│   ├── research_agent.py           # Agent 2: Requirements retrieval
│   ├── analysis_agent.py           # Agent 3: Report synthesis
│   └── orchestrator.py             # Pipeline coordinator
├── data/
│   └── visa_requirements.json      # UK & Schengen knowledge base
├── n8n/
│   └── visa_agent_phase1_workflow.json  # n8n workflow export
└── README.md
```

---

## n8n Workflow Setup

### Prerequisites
- n8n instance (cloud or self-hosted)
- OpenAI API credentials configured in n8n

### Import Instructions

1. Open your n8n instance
2. Go to **Workflows** → **Import from File**
3. Upload `n8n/visa_agent_phase1_workflow.json`
4. Open the imported workflow
5. Update the OpenAI credential on all LLM nodes (look for nodes named "Intake LLM", "Research LLM", "Analysis LLM")
6. Activate the workflow
7. Use the **Chat** interface to test

### n8n Workflow Nodes

| Node | Type | Purpose |
|---|---|---|
| Chat Trigger | LangChain Chat Trigger | Entry point for user messages |
| Intake Agent | LangChain AI Agent | Conversational interview |
| Intake LLM | OpenAI Chat Model | Powers the Intake Agent |
| Extract Applicant Profile | Code | Parses profile JSON from agent output |
| Profile Complete? | IF | Routes to pipeline or continues chat |
| Load Visa Requirements | Code | Loads UK/Schengen knowledge base |
| Research Agent | LangChain LLM Chain | Nationality-specific research |
| Research LLM | OpenAI Chat Model | Powers the Research Agent |
| Parse Research Output | Code | Parses supplementary notes |
| Analysis Agent | LangChain LLM Chain | Executive summary & guidance |
| Analysis LLM | OpenAI Chat Model | Powers the Analysis Agent |
| Build Final Report | Code | Assembles Markdown report |
| Return Report to Chat | Respond to Webhook | Delivers report to user |
| Continue Conversation | Respond to Webhook | Returns chat reply during intake |

---

## How It Works

### Phase 1 Pipeline

1. **Intake Agent** conducts a friendly conversational interview collecting:
   - Nationality, country of residence, destination
   - Purpose of visit, travel dates, number of travellers
   - Previous visa history and employment status

2. **Research Agent** retrieves requirements from the knowledge base and uses the LLM to generate nationality-specific supplementary notes, situation flags, and practical tips.

3. **Analysis Agent** synthesises everything into a structured report including:
   - Executive summary
   - Embassy selection guidance (Schengen)
   - ETA eligibility check (UK)
   - Full document checklist (mandatory + recommended)
   - Step-by-step application process
   - Official source links
   - Downloadable Markdown report

---

## Roadmap

| Phase | Scope |
|---|---|
| **Phase 1 (current)** | Intake + Research + Analysis — personalised requirements report |
| **Phase 2** | Document Submission Agent (guided mode — step-by-step form assistance) |
| **Phase 3** | Full form automation + Appointment Agent |
| **Phase 4** | Calendar sync + status tracking notifications |

---

## Important Disclaimer

This tool provides general information only. Visa requirements can change without notice. Always verify requirements with the official embassy or consulate before submitting an application. This system does not constitute legal or immigration advice.
