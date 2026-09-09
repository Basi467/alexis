"""Covers scheduler/deliver_calendar_check.py's heads-up message building --
the interview-prep tie-in that cross-references upcoming calendar events
against memory/job_tracker's tracked interviews, tailoring the announcement
instead of treating every event identically. web_research and ask_groq are
monkeypatched so these tests make no real network/API calls.
"""
import uuid

import pytest

import config
config.configure_logging()

from memory import job_tracker
import scheduler.deliver_calendar_check as deliver_calendar_check


@pytest.fixture
def unique_company():
    return f"ZzzTestCorp{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _cleanup_test_rows():
    yield
    job_tracker._conn.execute("DELETE FROM job_applications WHERE company LIKE 'ZzzTestCorp%'")
    job_tracker._conn.commit()
    job_tracker._load_index()


def test_no_matching_interview_uses_generic_message():
    events = [{"id": "1", "summary": "Dentist appointment"}, {"id": "2", "summary": "Team lunch"}]
    message = deliver_calendar_check._build_heads_up_message(events)
    assert message == "Heads up, you have Dentist appointment, Team lunch coming up soon."


def test_matching_interview_produces_tailored_message(unique_company, monkeypatch):
    job_tracker.upsert_application(unique_company, "Role", "interviewing")
    monkeypatch.setattr(
        "systems.web_research.search_and_read",
        lambda query: {"title": "Wiki", "url": "http://x", "text": f"{unique_company} is a software company."},
    )
    monkeypatch.setattr(
        "llm.groq_client.ask_groq",
        lambda prompt, model=None: (f"{unique_company} builds software.", None),
    )

    events = [{"id": "1", "summary": f"{unique_company} Screening Round"}]
    message = deliver_calendar_check._build_heads_up_message(events)

    assert f"your {unique_company} interview is coming up soon" in message
    assert "Good luck!" in message
    assert f"{unique_company} builds software." in message


def test_web_lookup_failure_falls_back_to_plain_heads_up(unique_company, monkeypatch):
    """A failed/empty search must never block the actual reminder from going
    out -- the company blurb is a nice-to-have, not load-bearing."""
    job_tracker.upsert_application(unique_company, "Role", "interviewing")
    monkeypatch.setattr("systems.web_research.search_and_read", lambda query: None)

    events = [{"id": "1", "summary": f"{unique_company} Screening Round"}]
    message = deliver_calendar_check._build_heads_up_message(events)

    assert message == f"Heads up, your {unique_company} interview is coming up soon. Good luck!"


def test_web_lookup_exception_falls_back_to_plain_heads_up(unique_company, monkeypatch):
    job_tracker.upsert_application(unique_company, "Role", "interviewing")

    def _raise(query):
        raise RuntimeError("network error")

    monkeypatch.setattr("systems.web_research.search_and_read", _raise)

    events = [{"id": "1", "summary": f"{unique_company} Screening Round"}]
    message = deliver_calendar_check._build_heads_up_message(events)

    assert message == f"Heads up, your {unique_company} interview is coming up soon. Good luck!"


def test_skip_blurb_response_falls_back_to_plain_heads_up(unique_company, monkeypatch):
    job_tracker.upsert_application(unique_company, "Role", "interviewing")
    monkeypatch.setattr(
        "systems.web_research.search_and_read",
        lambda query: {"title": "X", "url": "http://x", "text": "unrelated content"},
    )
    monkeypatch.setattr("llm.groq_client.ask_groq", lambda prompt, model=None: ("SKIP", None))

    events = [{"id": "1", "summary": f"{unique_company} Screening Round"}]
    message = deliver_calendar_check._build_heads_up_message(events)

    assert message == f"Heads up, your {unique_company} interview is coming up soon. Good luck!"


def test_other_events_appended_after_tailored_interview_message(unique_company, monkeypatch):
    job_tracker.upsert_application(unique_company, "Role", "interviewing")
    monkeypatch.setattr("systems.web_research.search_and_read", lambda query: None)

    events = [
        {"id": "1", "summary": f"{unique_company} Screening Round"},
        {"id": "2", "summary": "Dentist appointment"},
    ]
    message = deliver_calendar_check._build_heads_up_message(events)

    assert message.startswith(f"Heads up, your {unique_company} interview is coming up soon. Good luck!")
    assert "Also coming up: Dentist appointment." in message
