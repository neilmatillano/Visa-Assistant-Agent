"""
tracker.py — Progress tracker and appointment management for Phase 2

Provides functions to create, read, and update tracker items and
appointment records linked to a saved application.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, date
from typing import Optional

from agents.analysis_agent import VisaReport


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

class ItemStatus:
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    DONE        = "done"
    BLOCKED     = "blocked"
    NOT_NEEDED  = "not_needed"


class ItemType:
    DOCUMENT    = "document"
    STEP        = "step"
    APPOINTMENT = "appointment"
    SUBMISSION  = "submission"
    DECISION    = "decision"


STATUS_ICONS = {
    ItemStatus.PENDING:     "⏳",
    ItemStatus.IN_PROGRESS: "🔄",
    ItemStatus.DONE:        "✅",
    ItemStatus.BLOCKED:     "⚠️",
    ItemStatus.NOT_NEEDED:  "➖",
}

STATUS_LABELS = {
    ItemStatus.PENDING:     "Pending",
    ItemStatus.IN_PROGRESS: "In progress",
    ItemStatus.DONE:        "Done",
    ItemStatus.BLOCKED:     "Blocked",
    ItemStatus.NOT_NEEDED:  "Not needed",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_TRACKER_SCHEMA = """
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


def init_tracker_tables(conn: sqlite3.Connection) -> None:
    """Create tracker and appointment tables if not exist."""
    conn.executescript(_TRACKER_SCHEMA)


# ---------------------------------------------------------------------------
# Tracker item creation from VisaReport
# ---------------------------------------------------------------------------

def create_tracker_items(
    conn: sqlite3.Connection,
    application_id: int,
    report: VisaReport,
) -> list[int]:
    """
    Auto-generate tracker items from a VisaReport.
    Returns list of inserted row IDs.
    """
    now = datetime.now(timezone.utc).isoformat()
    items = []
    order = 0

    # --- Document items ---
    for doc in report.mandatory_documents:
        items.append((
            application_id,
            ItemType.DOCUMENT,
            doc.document,
            doc.details,
            ItemStatus.PENDING,
            report.upload_portal.url if report.upload_portal else None,
            "Upload portal" if report.upload_portal else None,
            None,
            order,
            now,
        ))
        order += 1

    for doc in report.optional_documents:
        items.append((
            application_id,
            ItemType.DOCUMENT,
            f"{doc.document} (recommended)",
            doc.details,
            ItemStatus.PENDING,
            report.upload_portal.url if report.upload_portal else None,
            "Upload portal" if report.upload_portal else None,
            None,
            order,
            now,
        ))
        order += 1

    # --- Application form download ---
    mandatory_forms = [f for f in report.forms if f.mandatory]
    for form in mandatory_forms:
        items.append((
            application_id,
            ItemType.STEP,
            f"Download & complete: {form.title}",
            form.description,
            ItemStatus.PENDING,
            form.url,
            f"Download {form.format}",
            form.notes,
            order,
            now,
        ))
        order += 1

    # --- Appointment booking ---
    if report.appointment_portals:
        portal = report.appointment_portals[0]
        items.append((
            application_id,
            ItemType.APPOINTMENT,
            f"Book appointment — {portal.name}",
            f"Estimated wait: ~{portal.avg_wait_weeks} weeks. {portal.notes}",
            ItemStatus.PENDING,
            portal.booking_url,
            "Book appointment",
            None,
            order,
            now,
        ))
        order += 1

    # --- Upload documents ---
    if report.upload_portal:
        items.append((
            application_id,
            ItemType.STEP,
            "Upload documents to portal",
            f"{report.upload_portal.name} · Accepted: {', '.join(report.upload_portal.accepted_formats)} · Max {report.upload_portal.max_file_mb}MB per file · {report.upload_portal.upload_timing}",
            ItemStatus.PENDING,
            report.upload_portal.login_url,
            "Open upload portal",
            report.upload_portal.notes,
            order,
            now,
        ))
        order += 1

    # --- Application steps (remaining steps not already captured) ---
    steps_added = {"book appointment", "upload", "download", "complete the form", "fill in"}
    for step in report.application_steps:
        step_lower = step.lower()
        if not any(kw in step_lower for kw in steps_added):
            items.append((
                application_id,
                ItemType.STEP,
                step,
                None,
                ItemStatus.PENDING,
                None,
                None,
                None,
                order,
                now,
            ))
            order += 1

    # --- Track application status ---
    if report.tracking_url:
        items.append((
            application_id,
            ItemType.DECISION,
            "Track application status",
            report.tracking_instructions or "Check your application status online using your reference number.",
            ItemStatus.PENDING,
            report.tracking_url,
            "Track application",
            None,
            order,
            now,
        ))
        order += 1

    # --- Receive decision ---
    items.append((
        application_id,
        ItemType.DECISION,
        "Receive visa decision",
        f"Expected within {report.processing_time}.",
        ItemStatus.PENDING,
        None,
        None,
        None,
        order,
        now,
    ))

    inserted_ids = []
    for item in items:
        cur = conn.execute("""
            INSERT INTO tracker_items
                (application_id, item_type, label, details, status,
                 link, link_label, notes, sort_order, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, item)
        inserted_ids.append(cur.lastrowid)

    conn.commit()
    return inserted_ids


# ---------------------------------------------------------------------------
# Tracker CRUD
# ---------------------------------------------------------------------------

def get_tracker_items(conn: sqlite3.Connection, application_id: int) -> list[dict]:
    """Return all tracker items for an application, ordered by sort_order."""
    rows = conn.execute("""
        SELECT * FROM tracker_items
        WHERE application_id = ?
        ORDER BY sort_order ASC
    """, (application_id,)).fetchall()
    return [dict(r) for r in rows]


def update_item_status(
    conn: sqlite3.Connection,
    item_id: int,
    status: str,
    notes: Optional[str] = None,
) -> bool:
    """Update a tracker item's status (and optionally notes)."""
    now = datetime.now(timezone.utc).isoformat()
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
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0] > 0


def get_progress(conn: sqlite3.Connection, application_id: int) -> dict:
    """
    Return a progress summary dict:
      total, done, in_progress, pending, blocked, pct_complete
    """
    rows = conn.execute("""
        SELECT status, COUNT(*) as cnt
        FROM tracker_items
        WHERE application_id = ?
        GROUP BY status
    """, (application_id,)).fetchall()

    counts = {r["status"]: r["cnt"] for r in rows}
    total  = sum(counts.values())
    done   = counts.get(ItemStatus.DONE, 0)
    not_needed = counts.get(ItemStatus.NOT_NEEDED, 0)
    pct    = round((done / max(total - not_needed, 1)) * 100)

    return {
        "total":       total,
        "done":        done,
        "in_progress": counts.get(ItemStatus.IN_PROGRESS, 0),
        "pending":     counts.get(ItemStatus.PENDING, 0),
        "blocked":     counts.get(ItemStatus.BLOCKED, 0),
        "not_needed":  not_needed,
        "pct_complete": pct,
    }


# ---------------------------------------------------------------------------
# Appointment management
# ---------------------------------------------------------------------------

def get_appointment(conn: sqlite3.Connection, application_id: int) -> Optional[dict]:
    """Return the appointment record for an application, or None."""
    row = conn.execute(
        "SELECT * FROM appointments WHERE application_id = ? ORDER BY id DESC LIMIT 1",
        (application_id,),
    ).fetchone()
    return dict(row) if row else None


def save_appointment(
    conn: sqlite3.Connection,
    application_id: int,
    portal_name: str,
    portal_url: str,
    appointment_date: Optional[str] = None,
    appointment_time: Optional[str] = None,
    location: Optional[str] = None,
    reference_number: Optional[str] = None,
    confirmation_notes: Optional[str] = None,
) -> int:
    """
    Insert or update the appointment record for an application.
    Returns the appointment row id.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM appointments WHERE application_id = ?",
        (application_id,),
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE appointments SET
                portal_name=?, portal_url=?, appointment_date=?,
                appointment_time=?, location=?, reference_number=?,
                confirmation_notes=?, status=?, updated_at=?
            WHERE application_id=?
        """, (
            portal_name, portal_url, appointment_date,
            appointment_time, location, reference_number,
            confirmation_notes,
            "booked" if reference_number else "pending",
            now, application_id,
        ))
        conn.commit()
        return existing["id"]
    else:
        cur = conn.execute("""
            INSERT INTO appointments
                (application_id, portal_name, portal_url, appointment_date,
                 appointment_time, location, reference_number,
                 confirmation_notes, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            application_id, portal_name, portal_url, appointment_date,
            appointment_time, location, reference_number,
            confirmation_notes,
            "booked" if reference_number else "pending",
            now, now,
        ))
        conn.commit()
        return cur.lastrowid


def generate_ics(
    application_id: int,
    portal_name: str,
    appointment_date: str,
    appointment_time: str,
    location: str,
    reference_number: str,
    visa_type: str,
) -> str:
    """
    Generate an iCalendar (.ics) string for the visa appointment.
    Returns the ICS content as a string ready for download.
    """
    from datetime import datetime as dt
    import uuid

    # Parse date/time (accept YYYY-MM-DD and HH:MM)
    try:
        appt_dt = dt.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            appt_dt = dt.strptime(appointment_date, "%Y-%m-%d")
            appt_dt = appt_dt.replace(hour=9, minute=0)
        except ValueError:
            appt_dt = dt.now()

    dtstart = appt_dt.strftime("%Y%m%dT%H%M%S")
    # Assume 1-hour appointment
    dtend_dt = appt_dt.replace(hour=appt_dt.hour + 1)
    dtend = dtend_dt.strftime("%Y%m%dT%H%M%S")
    dtstamp = dt.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid = str(uuid.uuid4())

    description = (
        f"Visa Application Appointment\\n"
        f"Visa type: {visa_type}\\n"
        f"Portal: {portal_name}\\n"
        f"Reference: {reference_number}\\n"
        f"\\nPlease bring all original documents and photocopies.\\n"
        f"Allow extra time to find the application centre."
    )

    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Visa Assistant//Phase 2//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{visa_type} appointment — {portal_name}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
        "STATUS:CONFIRMED",
        "BEGIN:VALARM",
        "TRIGGER:-PT24H",
        "ACTION:DISPLAY",
        "DESCRIPTION:Reminder: Visa appointment tomorrow",
        "END:VALARM",
        "BEGIN:VALARM",
        "TRIGGER:-PT2H",
        "ACTION:DISPLAY",
        "DESCRIPTION:Reminder: Visa appointment in 2 hours",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]) + "\r\n"


# ---------------------------------------------------------------------------
# Checklist PDF export
# ---------------------------------------------------------------------------

def build_tracker_pdf(items: list[dict], report: VisaReport, progress: dict) -> bytes:
    """Generate a PDF checklist of all tracker items."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm)

    GOLD  = colors.HexColor("#d4a843")
    DARK  = colors.HexColor("#1c2333")
    MUTED = colors.HexColor("#6e7681")
    GREEN = colors.HexColor("#3fb950")
    AMBER = colors.HexColor("#d29922")
    RED   = colors.HexColor("#f85149")

    styles = getSampleStyleSheet()
    title_s  = ParagraphStyle("T",  fontSize=18, textColor=GOLD,  spaceAfter=4, fontName="Helvetica-Bold")
    sub_s    = ParagraphStyle("S",  fontSize=10, textColor=MUTED,  spaceAfter=12)
    h2_s     = ParagraphStyle("H2", fontSize=12, textColor=GOLD,  spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold")
    body_s   = ParagraphStyle("B",  fontSize=9,  textColor=DARK,  leading=13, spaceAfter=3)
    note_s   = ParagraphStyle("N",  fontSize=8,  textColor=MUTED, leading=12, leftIndent=10)
    foot_s   = ParagraphStyle("F",  fontSize=7,  textColor=MUTED, alignment=TA_CENTER)

    story = []
    story.append(Paragraph(f"{report.visa_type} — Application Checklist", title_s))
    story.append(Paragraph(
        f"{report.applicant_nationality} → {report.destination_country} · {progress['pct_complete']}% complete "
        f"({progress['done']}/{progress['total']} items done)",
        sub_s))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=8))

    # Group items by type
    groups = {}
    for item in items:
        t = item["item_type"]
        groups.setdefault(t, []).append(item)

    labels_map = {
        ItemType.DOCUMENT: "Documents",
        ItemType.STEP: "Application steps",
        ItemType.APPOINTMENT: "Appointment",
        ItemType.SUBMISSION: "Submission",
        ItemType.DECISION: "Decision & tracking",
    }

    for itype, label in labels_map.items():
        group_items = groups.get(itype, [])
        if not group_items:
            continue
        story.append(Paragraph(label, h2_s))
        for item in group_items:
            icon = STATUS_ICONS.get(item["status"], "⏳")
            status_label = STATUS_LABELS.get(item["status"], item["status"])
            status_color = {
                ItemStatus.DONE: GREEN,
                ItemStatus.BLOCKED: AMBER,
                ItemStatus.IN_PROGRESS: GOLD,
            }.get(item["status"], MUTED)

            # Table row: [checkbox | label | status]
            data = [[
                Paragraph(f"{'☑' if item['status'] == ItemStatus.DONE else '☐'}", body_s),
                Paragraph(f"<b>{item['label']}</b>", body_s),
                Paragraph(f"<font color='#{status_color.hexval()[1:]}' size=8>{status_label}</font>", body_s),
            ]]
            t = Table(data, colWidths=[12*mm, 130*mm, 30*mm])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#21262d")),
            ]))
            story.append(t)
            if item.get("details"):
                story.append(Paragraph(item["details"], note_s))
            if item.get("notes"):
                story.append(Paragraph(f"Note: {item['notes']}", note_s))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Generated by Visa Application Assistant · Phase 2 · {datetime.now().strftime('%d %b %Y')}",
        foot_s
    ))

    doc.build(story)
    return buf.getvalue()
