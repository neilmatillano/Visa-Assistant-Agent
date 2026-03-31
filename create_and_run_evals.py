"""
Visa Application Assistant — OpenAI Evals API Setup
====================================================
This script:
1. Creates the Eval definition (schema + grading criteria) via POST /v1/evals
2. Uploads the dataset JSONL file via POST /v1/files
3. Creates an Eval Run that links the eval, dataset, and prompt via POST /v1/evals/{eval_id}/runs

Usage:
    pip install openai
    export OPENAI_API_KEY=sk-...
    python create_and_run_evals.py

The script will print the eval ID, file ID, run ID, and a direct link to view results
in the OpenAI dashboard.
"""

import io
import json
import os
import time
from pathlib import Path
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

DATASET_FILE = Path(__file__).parent / "visa_evals_dataset.jsonl"
MODEL = "gpt-4o-mini"  # Use a smaller model for faster evals; switch to gpt-5.4 for final grading

# ---------------------------------------------------------------------------
# Step 1: Create the Eval definition
# ---------------------------------------------------------------------------
print("Step 1: Creating eval definition...")

eval_obj = client.evals.create(
    name="Visa Application Multi-Agent System — Evaluation Suite",
    data_source_config={
        "type": "custom",
        "item_schema": {
            "type": "object",
            "properties": {
                "agent":               {"type": "string"},
                "test_id":             {"type": "string"},
                "description":         {"type": "string"},
                "expected_behaviour":  {"type": "string"},
                "pass_label":          {"type": "string"},
                "fail_label":          {"type": "string"},
                # Optional fields used by specific agents
                "conversation":        {"type": "array"},
                "profile":             {"type": "object"},
                "requirements":        {"type": "object"},
            },
            "required": ["agent", "test_id", "description", "expected_behaviour", "pass_label", "fail_label"]
        },
        "include_sample_schema": True
    },
    testing_criteria=[
        {
            "type": "label_model",
            "name": "Agent Quality — PASS/FAIL",
            "model": MODEL,
            "input": [
                {
                    "role": "developer",
                    "content": (
                        "You are an expert evaluator for a visa application AI assistant. "
                        "You will be given a test case description, the expected behaviour, "
                        "and the actual model output. "
                        "Evaluate whether the output meets the expected behaviour. "
                        "Respond with exactly one label: PASS or FAIL. "
                        "PASS means the output fully satisfies the expected behaviour. "
                        "FAIL means the output violates one or more criteria."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        "Agent being tested: {{ item.agent }}\n"
                        "Test: {{ item.description }}\n\n"
                        "Expected behaviour:\n{{ item.expected_behaviour }}\n\n"
                        "Model output to evaluate:\n{{ sample.output_text }}"
                    )
                }
            ],
            "labels": ["PASS", "FAIL"],
            "passing_labels": ["PASS"]
        }
    ]
)

eval_id = eval_obj.id
print(f"  ✓ Eval created: {eval_id}")

# ---------------------------------------------------------------------------
# Step 2: Read dataset, split by agent, upload a separate file per agent
# ---------------------------------------------------------------------------
print("\nStep 2: Splitting dataset by agent and uploading per-agent files...")

all_rows = []
with open(DATASET_FILE, "r") as f:
    for line in f:
        line = line.strip()
        if line:
            all_rows.append(json.loads(line))

agent_rows: dict[str, list] = {"intake": [], "research": [], "analysis": []}
for row in all_rows:
    agent_type = row.get("item", {}).get("agent")
    if agent_type in agent_rows:
        agent_rows[agent_type].append(row)

agent_file_ids: dict[str, str] = {}
for agent_type, rows in agent_rows.items():
    jsonl_bytes = "\n".join(json.dumps(r) for r in rows).encode("utf-8")
    file_obj = client.files.create(
        file=(f"visa_evals_{agent_type}.jsonl", io.BytesIO(jsonl_bytes)),
        purpose="evals",
    )
    agent_file_ids[agent_type] = file_obj.id
    print(f"  ✓ {agent_type} file uploaded: {file_obj.id}  ({len(rows)} rows)")

# Wait for all per-agent files to be processed
print("  Waiting for per-agent files to be processed...")
for agent_type, fid in agent_file_ids.items():
    for _ in range(10):
        status = client.files.retrieve(fid)
        if status.status == "processed":
            break
        time.sleep(2)
    print(f"  ✓ {agent_type} file status: {status.status}")

# ---------------------------------------------------------------------------
# Step 3: Create Eval Runs — one per agent type for clarity
# ---------------------------------------------------------------------------

def build_prompt_for_agent(agent_type: str) -> list:
    """Return the input_messages template for each agent type."""

    if agent_type == "intake":
        return [
            {
                "role": "developer",
                "content": (
                    "You are a visa application intake assistant. "
                    "Your job is to collect the applicant's profile through a friendly conversation. "
                    "You need ALL of these fields: nationality, country of residence, visa target (uk or schengen), "
                    "destination country, purpose of visit, travel dates, number of travellers, "
                    "previous visa refusal (yes/no), employment status. "
                    "VISA TARGET RULES — determine visa_target automatically from the destination, do NOT ask the user: "
                    "Schengen countries: Austria, Belgium, Czech Republic, Denmark, Estonia, Finland, France, Germany, "
                    "Greece, Hungary, Iceland, Italy, Latvia, Liechtenstein, Lithuania, Luxembourg, Malta, Netherlands, "
                    "Norway, Poland, Portugal, Slovakia, Slovenia, Spain, Sweden, Switzerland. "
                    "If the destination is any of those countries, set visa_target to 'schengen'. "
                    "If the destination is the United Kingdom, set visa_target to 'uk'. "
                    "TRAVEL DATES: approximate or descriptive dates (e.g. 'July for 2 weeks', 'next month for 4 days') are fully acceptable — do NOT ask for exact dates. "
                    "FIELD MAPPING — treat these natural language phrases as complete answers, do NOT re-ask or confirm: "
                    "'I travel alone' / 'just me' / 'only me' / 'traveling solo' = num_travellers is 1. "
                    "'I am a student' / 'I'm a student' = employment_status is Student. "
                    "'I am employed' / 'I'm employed' / 'I work as ...' = employment_status is Employed. "
                    "'I am self-employed' / 'I run my own business' = employment_status is Self-employed. "
                    "'No refusals' / 'no previous refusal' / 'never been refused' = previous_visa_refusal is false. "
                    "'I had a refusal' / 'I was refused' / 'I had a ... refusal' = previous_visa_refusal is true. "
                    "Once ALL 9 fields are collected, output the JSON block IMMEDIATELY — no confirmation, no follow-up questions:\n"
                    "```json\n{\"profile_complete\": true, \"nationality\": \"...\", ...}\n```\n"
                    "NEVER ask for information already provided in the conversation. "
                    "NEVER output the profile_complete JSON block if ANY required field is missing — do NOT assume or infer missing fields. "
                    "If all 9 fields are present, output the JSON in your very next response — do NOT ask to confirm or clarify first."
                )
            },
            {
                "role": "user",
                "content": (
                    "Here is the conversation so far:\n{{ item.conversation }}\n\n"
                    "Continue the conversation as the intake assistant. "
                    "If all required fields are now collected, output the complete profile JSON."
                )
            }
        ]

    elif agent_type == "research":
        return [
            {
                "role": "developer",
                "content": (
                    "You are a visa requirements research agent. "
                    "Given an applicant profile, research and return structured visa requirements. "
                    "Return a JSON object with: visa_type, authority, apply_url, info_url, fee, "
                    "processing_time, max_stay, required_documents (array of {name, details, mandatory}), "
                    "application_steps (array of strings), key_notes (array of strings), "
                    "official_sources (array of {title, url}), nationality_specific_notes, "
                    "risk_flags (array of strings). "
                    "IMPORTANT visa type rules: "
                    "(1) If the destination is the UK, return UK Standard Visitor Visa requirements with fees in GBP and apply_url pointing to gov.uk — never return Schengen requirements. "
                    "(2) For Schengen destinations, a stay over 90 days OR a purpose of Study or Work requires a National Visa (Type D), not a Short-Stay Visa (Type C). "
                    "(3) If previous_schengen_refusal or previous_uk_refusal is true, required_documents must include a cover letter or explanation letter addressing the prior refusal."
                )
            },
            {
                "role": "user",
                "content": "Profile: {{ item.profile }}"
            }
        ]

    elif agent_type == "analysis":
        return [
            {
                "role": "developer",
                "content": (
                    "You are a senior visa consultant producing a clear, actionable visa requirements report. "
                    "Given a research result, produce a concise executive summary (3–4 sentences) that: "
                    "1. States the visa type and destination. "
                    "2. Summarises the key requirements and fees. "
                    "3. Highlights any important considerations for this specific applicant. "
                    "4. Ends with a reassuring, professional tone. "
                    "Also determine: whether the applicant needs to apply at a specific embassy "
                    "(for Schengen, based on their itinerary); any ETA eligibility (for UK, based on nationality); "
                    "any special flags that should be prominently displayed. "
                    "Flagging rules for priority_flags: "
                    "- If employment_status is Self-employed, always include a flag that explicitly identifies self-employment as a financial evidence risk, e.g. 'Self-employment is a financial evidence risk — provide bank statements and business registration documents.' "
                    "- If there is a previous visa refusal, always include a flag explicitly naming the prior refusal as a risk factor. "
                    "Respond in JSON format: "
                    "{\"executive_summary\": \"...\", \"embassy_guidance\": \"...\", "
                    "\"eta_eligible\": false, \"eta_note\": \"...\", "
                    "\"priority_flags\": [\"...\", \"...\"]}"
                )
            },
            {
                "role": "user",
                "content": "Profile: {{ item.profile }}\n\nRequirements: {{ item.requirements }}"
            }
        ]

    return []


run_ids = {}
for agent in ["intake", "research", "analysis"]:
    print(f"\nStep 3: Creating eval run for {agent} agent...")

    run = client.evals.runs.create(
        eval_id=eval_id,
        name=f"Visa Agent Eval — {agent.capitalize()} Agent",
        data_source={
            "type": "responses",
            "model": MODEL,
            "input_messages": {
                "type": "template",
                "template": build_prompt_for_agent(agent)
            },
            "source": {
                "type": "file_id",
                "id": agent_file_ids[agent]
            }
        }
    )

    run_ids[agent] = run.id
    print(f"  ✓ Run created: {run.id}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("SETUP COMPLETE")
print("=" * 60)
print(f"Eval ID:    {eval_id}")
for agent_type, fid in agent_file_ids.items():
    print(f"File ID ({agent_type}): {fid}")
print()
for agent, run_id in run_ids.items():
    print(f"{agent.capitalize()} Agent Run ID: {run_id}")
print()
print("View results in the dashboard:")
print(f"  https://platform.openai.com/evaluation/evals/{eval_id}")
print()
print("Note: Runs process asynchronously. Check the dashboard in a few minutes.")
print("=" * 60)

# Save IDs to a file for reference
ids = {
    "eval_id": eval_id,
    "file_ids": agent_file_ids,
    "run_ids": run_ids
}
output_path = Path(__file__).parent / "eval_ids.json"
with open(output_path, "w") as f:
    json.dump(ids, f, indent=2)
print(f"\nIDs saved to: {output_path}")
