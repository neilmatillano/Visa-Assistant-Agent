"""
database.py — Persistent storage for Visa Application Multi-Agent System

Uses SQLite (via Python's built-in sqlite3) so no extra dependencies are needed.
The database file is created automatically at `visa_agent/data/applications.db`.

Schema
------
applications
    id              INTEGER  PRIMARY KEY AUTOINCREMENT
    created_at      TEXT     ISO-8601 UTC timestamp
    status          TEXT     'complete' | 'error' | 'in_progress'
    -- Applicant profile --
    nationality             TEXT
    country_of_residence    TEXT
    destination_country     TEXT
    destination_city        TEXT
    purpose_of_visit        TEXT
    travel_start_date       TEXT
    travel_end_date         TEXT
    duration_days           INTEGER
    num_travellers          INTEGER
    has_previous_uk_visa    INTEGER  (0/1/NULL)
    has_previous_schengen   INTEGER  (0/1/NULL)
    has_previous_refusal    INTEGER  (0/1/NULL)
    employment_status       TEXT
    visa_target             TEXT     'uk' | 'schengen'
    schengen_main_country   TEXT
    -- Report summary --
    visa_type               TEXT
    fee                     TEXT
    processing_time         TEXT
    max_stay                TEXT
    apply_url               TEXT
    executive_summary       TEXT
    -- Full JSON blobs --
    profile_json            TEXT     JSON of full ApplicantProfile
    report_json             TEXT     JSON of full VisaReport
    chat_history_json       TEXT     JSON list of chat messages
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional

from agents.intake_agent import ApplicantProfile
from agents.analysis_agent import VisaReport, DocumentItem


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

_DB_DIR  = os.path.join(os.path.dirname(__file__), "data")
_DB_PATH = os.path.join(_DB_DIR, "applications.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Schema initialisation
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at              TEXT    NOT NULL,
    status                  TEXT    NOT NULL DEFAULT 'in_progress',
    nationality             TEXT,
    country_of_residence    TEXT,
    destination_country     TEXT,
    destination_city        TEXT,
    purpose_of_visit        TEXT,
    travel_start_date       TEXT,
    travel_end_date         TEXT,
    duration_days           INTEGER,
    num_travellers          INTEGER,
    has_previous_uk_visa    INTEGER,
    has_previous_schengen   INTEGER,
    has_previous_refusal    INTEGER,
    employment_status       TEXT,
    visa_target             TEXT,
    schengen_main_country   TEXT,
    visa_type               TEXT,
    fee                     TEXT,
    processing_time         TEXT,
    max_stay                TEXT,
    apply_url               TEXT,
    executive_summary       TEXT,
    profile_json            TEXT,
    report_json             TEXT,
    chat_history_json       TEXT
);
"""


def init_db() -> None:
    """Create the database and tables if they do not exist."""
    with _get_conn() as conn:
        conn.executescript(_CREATE_SQL)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _profile_to_dict(profile: ApplicantProfile) -> dict:
    return profile.model_dump()


def _report_to_dict(report: VisaReport) -> dict:
    """Convert VisaReport (dataclass) to a JSON-serialisable dict."""
    def _doc(d: DocumentItem) -> dict:
        return {"id": d.id, "document": d.document, "details": d.details,
                "mandatory": d.mandatory, "status": d.status}
    return {
        "visa_type": report.visa_type,
        "applicant_nationality": report.applicant_nationality,
        "country_of_residence": report.country_of_residence,
        "destination_country": report.destination_country,
        "purpose_of_visit": report.purpose_of_visit,
        "schengen_main_country": report.schengen_main_country,
        "fee": report.fee,
        "processing_time": report.processing_time,
        "max_stay": report.max_stay,
        "apply_url": report.apply_url,
        "mandatory_documents": [_doc(d) for d in report.mandatory_documents],
        "optional_documents":  [_doc(d) for d in report.optional_documents],
        "application_steps": report.application_steps,
        "key_notes": report.key_notes,
        "supplementary_notes": report.supplementary_notes,
        "sources": report.sources,
        "embassy_guidance": report.embassy_guidance,
        "eta_eligible": report.eta_eligible,
        "eta_note": report.eta_note,
        "executive_summary": report.executive_summary,
    }


def _dict_to_report(d: dict) -> VisaReport:
    """Reconstruct a VisaReport from a stored dict."""
    def _doc(x: dict) -> DocumentItem:
        return DocumentItem(id=x["id"], document=x["document"], details=x["details"],
                            mandatory=x["mandatory"], status=x.get("status", "pending"))
    return VisaReport(
        visa_type=d["visa_type"],
        applicant_nationality=d["applicant_nationality"],
        country_of_residence=d["country_of_residence"],
        destination_country=d["destination_country"],
        purpose_of_visit=d["purpose_of_visit"],
        schengen_main_country=d.get("schengen_main_country"),
        fee=d["fee"],
        processing_time=d["processing_time"],
        max_stay=d["max_stay"],
        apply_url=d["apply_url"],
        mandatory_documents=[_doc(x) for x in d.get("mandatory_documents", [])],
        optional_documents=[_doc(x) for x in d.get("optional_documents", [])],
        application_steps=d.get("application_steps", []),
        key_notes=d.get("key_notes", []),
        supplementary_notes=d.get("supplementary_notes", []),
        sources=d.get("sources", []),
        embassy_guidance=d.get("embassy_guidance"),
        eta_eligible=d.get("eta_eligible", False),
        eta_note=d.get("eta_note"),
        executive_summary=d.get("executive_summary", ""),
    )


def _dict_to_profile(d: dict) -> ApplicantProfile:
    return ApplicantProfile(**d)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def save_application(
    profile: ApplicantProfile,
    report: VisaReport,
    chat_history: list[dict],
    status: str = "complete",
) -> int:
    """
    Insert or replace a completed application record.
    Returns the new row id.
    """
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    profile_dict = _profile_to_dict(profile)
    report_dict  = _report_to_dict(report)

    with _get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO applications (
                created_at, status,
                nationality, country_of_residence, destination_country,
                destination_city, purpose_of_visit,
                travel_start_date, travel_end_date, duration_days,
                num_travellers, has_previous_uk_visa, has_previous_schengen,
                has_previous_refusal, employment_status,
                visa_target, schengen_main_country,
                visa_type, fee, processing_time, max_stay, apply_url,
                executive_summary,
                profile_json, report_json, chat_history_json
            ) VALUES (
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?,
                ?,
                ?, ?, ?
            )
        """, (
            now, status,
            profile.nationality, profile.country_of_residence, profile.destination_country,
            profile.destination_city, profile.purpose_of_visit,
            profile.travel_start_date, profile.travel_end_date, profile.duration_days,
            profile.num_travellers,
            int(profile.has_previous_uk_visa) if profile.has_previous_uk_visa is not None else None,
            int(profile.has_previous_schengen_visa) if profile.has_previous_schengen_visa is not None else None,
            int(profile.has_previous_refusal) if profile.has_previous_refusal is not None else None,
            profile.employment_status,
            profile.visa_target, profile.schengen_main_country,
            report.visa_type, report.fee, report.processing_time, report.max_stay, report.apply_url,
            report.executive_summary,
            json.dumps(profile_dict), json.dumps(report_dict), json.dumps(chat_history),
        ))
        return cur.lastrowid


def list_applications(limit: int = 50) -> list[dict]:
    """
    Return a summary list of all applications, newest first.
    Each dict contains: id, created_at, status, nationality, destination_country,
    visa_type, visa_target, purpose_of_visit, num_travellers.
    """
    init_db()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT id, created_at, status,
                   nationality, country_of_residence, destination_country,
                   visa_type, visa_target, purpose_of_visit, num_travellers,
                   executive_summary, fee, processing_time, max_stay
            FROM applications
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_application(app_id: int) -> Optional[dict]:
    """
    Return the full application record including reconstructed profile and report objects.
    Returns None if not found.
    """
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()

    if not row:
        return None

    data = dict(row)
    # Reconstruct objects from JSON blobs
    try:
        data["profile_obj"] = _dict_to_profile(json.loads(data["profile_json"]))
    except Exception:
        data["profile_obj"] = None
    try:
        data["report_obj"] = _dict_to_report(json.loads(data["report_json"]))
    except Exception:
        data["report_obj"] = None
    try:
        data["chat_history"] = json.loads(data["chat_history_json"] or "[]")
    except Exception:
        data["chat_history"] = []
    return data


def delete_application(app_id: int) -> bool:
    """Delete an application by id. Returns True if a row was deleted."""
    init_db()
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    return cur.rowcount > 0


def get_stats() -> dict:
    """Return aggregate statistics across all applications."""
    init_db()
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        uk    = conn.execute("SELECT COUNT(*) FROM applications WHERE visa_target='uk'").fetchone()[0]
        sch   = conn.execute("SELECT COUNT(*) FROM applications WHERE visa_target='schengen'").fetchone()[0]
        top_dest = conn.execute("""
            SELECT destination_country, COUNT(*) as cnt
            FROM applications
            GROUP BY destination_country
            ORDER BY cnt DESC LIMIT 5
        """).fetchall()
    return {
        "total": total,
        "uk": uk,
        "schengen": sch,
        "top_destinations": [dict(r) for r in top_dest],
    }
