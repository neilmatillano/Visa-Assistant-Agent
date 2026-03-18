"""
database.py — Persistent storage for Visa Application Multi-Agent System (Phase 2)

Schema additions vs Phase 1
────────────────────────────
tracker_items   per-application progress checklist rows
appointments    appointment booking records (date, reference, .ics)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from agents.intake_agent import ApplicantProfile
from agents.analysis_agent import (
    VisaReport, DocumentItem, FormLink, UploadPortal,
    AppointmentPortal,
)


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

_DB_DIR  = os.path.join(os.path.dirname(__file__), "data")
_DB_PATH = os.path.join(_DB_DIR, "applications.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Schema
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

CREATE TABLE IF NOT EXISTS tracker_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL,
    item_type       TEXT    NOT NULL,
    label           TEXT    NOT NULL,
    details         TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',
    link            TEXT,
    link_label      TEXT,
    notes           TEXT,
    sort_order      INTEGER DEFAULT 0,
    updated_at      TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS appointments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id      INTEGER NOT NULL,
    portal_name         TEXT,
    portal_url          TEXT,
    appointment_date    TEXT,
    appointment_time    TEXT,
    location            TEXT,
    reference_number    TEXT,
    confirmation_notes  TEXT,
    ics_content         TEXT,
    status              TEXT NOT NULL DEFAULT 'not_booked',
    created_at          TEXT,
    updated_at          TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);
"""


def init_db() -> None:
    """Create all tables if they do not exist."""
    with _get_conn() as conn:
        conn.executescript(_CREATE_SQL)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _profile_to_dict(profile: ApplicantProfile) -> dict:
    return profile.model_dump()


def _doc_to_dict(d: DocumentItem) -> dict:
    return {
        "id": d.id, "document": d.document, "details": d.details,
        "mandatory": d.mandatory, "status": d.status,
        "upload_format": d.upload_format, "max_file_mb": d.max_file_mb,
    }


def _form_to_dict(f: FormLink) -> dict:
    return {
        "id": f.id, "title": f.title, "description": f.description,
        "url": f.url, "format": f.format, "mandatory": f.mandatory, "notes": f.notes,
    }


def _portal_to_dict(p: Optional[UploadPortal]) -> Optional[dict]:
    if p is None:
        return None
    return {
        "name": p.name, "url": p.url, "login_url": p.login_url,
        "accepted_formats": p.accepted_formats, "max_file_mb": p.max_file_mb,
        "notes": p.notes, "upload_timing": p.upload_timing,
        "login_instructions": p.login_instructions,
    }


def _appt_portal_to_dict(a: AppointmentPortal) -> dict:
    return {
        "name": a.name, "url": a.url, "booking_url": a.booking_url,
        "avg_wait_weeks": a.avg_wait_weeks, "notes": a.notes,
        "booking_steps": a.booking_steps, "locations_info_url": a.locations_info_url,
    }


def _report_to_dict(report: VisaReport) -> dict:
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
        "mandatory_documents": [_doc_to_dict(d) for d in report.mandatory_documents],
        "optional_documents":  [_doc_to_dict(d) for d in report.optional_documents],
        "application_steps": report.application_steps,
        "key_notes": report.key_notes,
        "supplementary_notes": report.supplementary_notes,
        "sources": report.sources,
        "embassy_guidance": report.embassy_guidance,
        "eta_eligible": report.eta_eligible,
        "eta_note": report.eta_note,
        "executive_summary": report.executive_summary,
        # Phase 2
        "forms": [_form_to_dict(f) for f in report.forms],
        "upload_portal": _portal_to_dict(report.upload_portal),
        "appointment_portals": [_appt_portal_to_dict(a) for a in report.appointment_portals],
        "tracking_url": report.tracking_url,
        "tracking_instructions": report.tracking_instructions,
    }


def _dict_to_report(d: dict) -> VisaReport:
    def _doc(x: dict) -> DocumentItem:
        return DocumentItem(
            id=x["id"], document=x["document"], details=x["details"],
            mandatory=x["mandatory"], status=x.get("status", "pending"),
            upload_format=x.get("upload_format", "PDF"),
            max_file_mb=x.get("max_file_mb", 2),
        )

    def _form(x: dict) -> FormLink:
        return FormLink(
            id=x["id"], title=x["title"], description=x["description"],
            url=x["url"], format=x["format"], mandatory=x.get("mandatory", False),
            notes=x.get("notes", ""),
        )

    def _portal(x: Optional[dict]) -> Optional[UploadPortal]:
        if not x:
            return None
        return UploadPortal(
            name=x["name"], url=x["url"], login_url=x.get("login_url", x["url"]),
            accepted_formats=x.get("accepted_formats", ["PDF"]),
            max_file_mb=x.get("max_file_mb", 2),
            notes=x.get("notes", ""),
            upload_timing=x.get("upload_timing", "Before appointment"),
            login_instructions=x.get("login_instructions", []),
        )

    def _appt_portal(x: dict) -> AppointmentPortal:
        return AppointmentPortal(
            name=x["name"], url=x["url"], booking_url=x["booking_url"],
            avg_wait_weeks=x.get("avg_wait_weeks", 3),
            notes=x.get("notes", ""),
            booking_steps=x.get("booking_steps", []),
            locations_info_url=x.get("locations_info_url", x["url"]),
        )

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
        forms=[_form(x) for x in d.get("forms", [])],
        upload_portal=_portal(d.get("upload_portal")),
        appointment_portals=[_appt_portal(x) for x in d.get("appointment_portals", [])],
        tracking_url=d.get("tracking_url", ""),
        tracking_instructions=d.get("tracking_instructions", ""),
    )


def _dict_to_profile(d: dict) -> ApplicantProfile:
    return ApplicantProfile(**d)


# ─────────────────────────────────────────────────────────────────────────────
# Public API — Applications
# ─────────────────────────────────────────────────────────────────────────────

def save_application(
    profile: ApplicantProfile,
    report: VisaReport,
    chat_history: list[dict],
    status: str = "complete",
) -> int:
    """Insert a completed application. Returns the new row id."""
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
        app_id = cur.lastrowid

        # Auto-generate tracker items for Phase 2
        try:
            from agents.tracker import create_tracker_items
            create_tracker_items(conn, app_id, report)
        except Exception as e:
            print(f"[tracker] Failed to create tracker items: {e}")

        return app_id


def list_applications(limit: int = 50) -> list[dict]:
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
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()

    if not row:
        return None

    data = dict(row)
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
    init_db()
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    return cur.rowcount > 0


def get_stats() -> dict:
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


# ─────────────────────────────────────────────────────────────────────────────
# Public API — Tracker
# ─────────────────────────────────────────────────────────────────────────────

def get_tracker_items(app_id: int) -> list[dict]:
    init_db()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM tracker_items
            WHERE application_id = ?
            ORDER BY sort_order ASC
        """, (app_id,)).fetchall()
    return [dict(r) for r in rows]


def update_tracker_item(item_id: int, status: str, notes: Optional[str] = None) -> bool:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        if notes is not None:
            conn.execute(
                "UPDATE tracker_items SET status=?, notes=?, updated_at=? WHERE id=?",
                (status, notes, now, item_id),
            )
        else:
            conn.execute(
                "UPDATE tracker_items SET status=?, updated_at=? WHERE id=?",
                (status, now, item_id),
            )
    return True


def get_progress(app_id: int) -> dict:
    init_db()
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) as cnt FROM tracker_items
            WHERE application_id = ?
            GROUP BY status
        """, (app_id,)).fetchall()
    counts = {r["status"]: r["cnt"] for r in rows}
    total  = sum(counts.values())
    done   = counts.get("done", 0)
    not_needed = counts.get("not_needed", 0)
    pct    = round((done / max(total - not_needed, 1)) * 100) if total else 0
    return {
        "total":       total,
        "done":        done,
        "in_progress": counts.get("in_progress", 0),
        "pending":     counts.get("pending", 0),
        "blocked":     counts.get("blocked", 0),
        "not_needed":  not_needed,
        "pct_complete": pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API — Appointments
# ─────────────────────────────────────────────────────────────────────────────

def get_appointment(app_id: int) -> Optional[dict]:
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM appointments WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (app_id,),
        ).fetchone()
    return dict(row) if row else None


def save_appointment(
    app_id: int,
    portal_name: str,
    portal_url: str,
    appointment_date: Optional[str] = None,
    appointment_time: Optional[str] = None,
    location: Optional[str] = None,
    reference_number: Optional[str] = None,
    confirmation_notes: Optional[str] = None,
    ics_content: Optional[str] = None,
) -> int:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM appointments WHERE application_id = ?", (app_id,)
        ).fetchone()
        appt_status = "booked" if reference_number else "pending"

        if existing:
            conn.execute("""
                UPDATE appointments SET
                    portal_name=?, portal_url=?, appointment_date=?,
                    appointment_time=?, location=?, reference_number=?,
                    confirmation_notes=?, ics_content=?, status=?, updated_at=?
                WHERE application_id=?
            """, (
                portal_name, portal_url, appointment_date,
                appointment_time, location, reference_number,
                confirmation_notes, ics_content, appt_status, now, app_id,
            ))
            row_id = existing["id"]
        else:
            cur = conn.execute("""
                INSERT INTO appointments
                    (application_id, portal_name, portal_url, appointment_date,
                     appointment_time, location, reference_number,
                     confirmation_notes, ics_content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                app_id, portal_name, portal_url, appointment_date,
                appointment_time, location, reference_number,
                confirmation_notes, ics_content, appt_status, now, now,
            ))
            row_id = cur.lastrowid

        # Update matching tracker item to done if booked
        if reference_number:
            conn.execute("""
                UPDATE tracker_items
                SET status='done', updated_at=?
                WHERE application_id=? AND item_type='appointment'
            """, (now, app_id))

    return row_id
