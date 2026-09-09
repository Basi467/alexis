"""Turns email-reading into an actual queryable record of the user's job
search. check_email / the background email monitor already read job-related
emails, but previously just announced them once and forgot -- this remembers
them as a status-tracked pipeline (company, role, status) the user can query
later ("what's the status of my Amazon application"). Company matching
mirrors memory/store.py's _find_project_by_name: exact -> substring ->
semantic, so "Amazon" and "amazon.com recruiting" land on the same row
instead of fragmenting into duplicates.
"""
import logging
import sqlite3
from datetime import datetime, timezone

from config import MEMORY_DB_FILE
from embedding_model import embedder
from memory.db import VectorIndex, blob_to_vector, connect, vector_to_blob

logger = logging.getLogger(__name__)

STATUSES = {"applied", "interviewing", "offer", "rejected", "other"}

_conn = connect(MEMORY_DB_FILE)

_conn.execute("""
    CREATE TABLE IF NOT EXISTS job_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        role TEXT,
        status TEXT NOT NULL,
        embedding BLOB NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
""")
# Separate from the applications table itself since one email updates a row
# that already exists (e.g. a rejection updating an "applied" row) -- this
# just needs to answer "have we already extracted this specific email",
# independent of which (if any) application row it ended up touching.
_conn.execute("""
    CREATE TABLE IF NOT EXISTS processed_application_emails (
        email_id TEXT PRIMARY KEY
    )
""")
_conn.commit()

_applications_index = VectorIndex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _embed(text: str):
    return embedder.encode([text], show_progress_bar=False)[0]


def _load_index() -> None:
    rows = _conn.execute("SELECT id, embedding FROM job_applications").fetchall()
    _applications_index.load(
        [row["id"] for row in rows],
        [blob_to_vector(row["embedding"]) for row in rows],
    )


_load_index()


def _find_application_by_company(company: str, distance_threshold: float = 1.2) -> sqlite3.Row | None:
    exact = _conn.execute(
        "SELECT * FROM job_applications WHERE lower(company) = lower(?)", (company,)
    ).fetchone()
    if exact:
        return exact

    substring = _conn.execute(
        "SELECT * FROM job_applications WHERE lower(?) LIKE '%' || lower(company) || '%' "
        "OR lower(company) LIKE '%' || lower(?) || '%' "
        "ORDER BY length(company) DESC LIMIT 1",
        (company, company),
    ).fetchone()
    if substring:
        return substring

    vector = _embed(company)
    matches = _applications_index.search(vector, k=1)
    if matches and matches[0][1] < distance_threshold:
        app_id, _ = matches[0]
        return _conn.execute("SELECT * FROM job_applications WHERE id = ?", (app_id,)).fetchone()

    return None


def is_email_processed(email_id: str) -> bool:
    row = _conn.execute(
        "SELECT 1 FROM processed_application_emails WHERE email_id = ?", (email_id,)
    ).fetchone()
    return row is not None


def mark_email_processed(email_id: str) -> None:
    _conn.execute(
        "INSERT OR IGNORE INTO processed_application_emails (email_id) VALUES (?)", (email_id,)
    )
    _conn.commit()


def upsert_application(company: str, role: str | None, status: str, notes: str | None = None) -> dict:
    """Creates a new tracked application, or updates the status/role of an
    existing one for the same company (see _find_application_by_company) --
    so a later interview-invite or rejection email updates the same row an
    earlier "applied" email created, instead of fragmenting into duplicates."""
    status = status.lower().strip()
    if status not in STATUSES:
        status = "other"

    existing = _find_application_by_company(company)
    vector = _embed(f"{company} {role or ''}")
    now = _now()

    if existing:
        app_id = existing["id"]
        final_role = role or existing["role"]
        _conn.execute(
            "UPDATE job_applications SET role = ?, status = ?, embedding = ?, "
            "notes = COALESCE(?, notes), updated_at = ? WHERE id = ?",
            (final_role, status, vector_to_blob(vector), notes, now, app_id),
        )
        _applications_index.upsert(app_id, vector)
        logger.info("Updated job application for %r (id=%d) -> status=%s", company, app_id, status)
    else:
        app_id = _conn.execute(
            "INSERT INTO job_applications (company, role, status, embedding, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (company, role, status, vector_to_blob(vector), notes, now, now),
        ).lastrowid
        _applications_index.upsert(app_id, vector)
        logger.info("Tracked new job application for %r -> status=%s", company, status)

    _conn.commit()
    return dict(_conn.execute("SELECT * FROM job_applications WHERE id = ?", (app_id,)).fetchone())


def list_applications(status_filter: str | None = None) -> list[dict]:
    if status_filter:
        rows = _conn.execute(
            "SELECT * FROM job_applications WHERE lower(status) = lower(?) ORDER BY updated_at DESC",
            (status_filter,),
        ).fetchall()
    else:
        rows = _conn.execute(
            "SELECT * FROM job_applications ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_application(company: str) -> dict | None:
    row = _find_application_by_company(company)
    return dict(row) if row else None


def find_interview_application_for_event(event_title: str) -> dict | None:
    """Checks whether event_title mentions any company currently tracked as
    "interviewing" -- lets the calendar monitor recognize that a given event
    IS a specific tracked interview (not just any calendar event), so its
    heads-up can be tailored instead of generic. Substring match only, not the
    full exact/substring/semantic pipeline _find_application_by_company uses --
    calendar event titles are short and specific enough ("Coorix Screening
    Round") that a plain substring check is reliable here without embeddings."""
    interviewing = list_applications(status_filter="interviewing")
    if not interviewing:
        return None

    lowered_title = event_title.lower()
    for app in interviewing:
        if app["company"].lower() in lowered_title:
            return app
    return None


def describe_job_status() -> str:
    """A short, positive-toned summary for the morning briefing -- upcoming
    interviews (actionable, worth a heads-up) and a pending count (reassuring
    progress signal). Deliberately does NOT mention rejections here -- leading
    a cheerful wake-up message with bad news isn't the point of a briefing,
    and the full picture (rejections included) is always available on request
    via "what's the status of my applications"."""
    apps = list_applications()
    if not apps:
        return ""

    interviewing = [a for a in apps if a["status"] == "interviewing"]
    pending = [a for a in apps if a["status"] == "applied"]

    parts = []
    if interviewing:
        names = ", ".join(a["company"] for a in interviewing)
        if len(interviewing) == 1:
            parts.append(f"you have an interview coming up with {names}")
        else:
            parts.append(f"you have interviews coming up with {names}")
    if pending:
        parts.append(f"{len(pending)} application{'s' if len(pending) != 1 else ''} still pending")

    if not parts:
        return ""
    return "On the job front, " + " and ".join(parts) + "."
