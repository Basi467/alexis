"""Covers memory/job_tracker.py's company-matching logic (exact -> substring
-> semantic fallback) -- the same 3-tier pattern memory/store.py uses for
projects, and the thing that decides whether a rejection email correctly
updates the SAME row an earlier "applied" email created, or wrongly creates a
duplicate.

This module's functions operate on the real, shared SQLite/FAISS-backed
database (there's no dependency-injection seam for a test database without a
larger refactor), so every test uses obviously-fake, uniquely-prefixed company
names and cleans its own rows up afterward via a fixture -- never touches or
leaves behind anything resembling the user's real tracked applications.
"""
import uuid

import pytest

import config
config.configure_logging()

from memory import job_tracker


@pytest.fixture
def unique_company():
    """A company name that cannot plausibly collide with real user data,
    scoped fresh to each test so tests can't interfere with each other."""
    return f"ZzzTestCorp{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _cleanup_test_rows():
    """Deletes any row whose company starts with the test prefix after every
    test, regardless of pass/fail, so a broken test can't leave junk in the
    real database."""
    yield
    job_tracker._conn.execute("DELETE FROM job_applications WHERE company LIKE 'ZzzTestCorp%'")
    job_tracker._conn.execute("DELETE FROM processed_application_emails WHERE email_id LIKE 'zzz-test-%'")
    job_tracker._conn.commit()
    job_tracker._load_index()  # rebuild the in-memory FAISS index to match


def test_new_application_is_created(unique_company):
    app = job_tracker.upsert_application(unique_company, "Software Engineer", "applied")
    assert app["company"] == unique_company
    assert app["role"] == "Software Engineer"
    assert app["status"] == "applied"

    fetched = job_tracker.get_application(unique_company)
    assert fetched is not None
    assert fetched["id"] == app["id"]


def test_exact_match_updates_instead_of_duplicating(unique_company):
    first = job_tracker.upsert_application(unique_company, "Software Engineer", "applied")
    second = job_tracker.upsert_application(unique_company, None, "interviewing")

    assert second["id"] == first["id"], "same exact company name must update the same row"
    assert second["status"] == "interviewing"
    assert second["role"] == "Software Engineer", "role should be preserved when a later update omits it"

    all_matching = job_tracker.list_applications()
    matching_ids = [a["id"] for a in all_matching if a["company"] == unique_company]
    assert len(matching_ids) == 1, "must not have created a duplicate row"


def test_substring_match_updates_the_same_row(unique_company):
    first = job_tracker.upsert_application(unique_company, "Backend Engineer", "applied")
    second = job_tracker.upsert_application(f"{unique_company.lower()}.com recruiting", None, "rejected")

    assert second["id"] == first["id"], "a substring/case-variant company name should still match the existing row"
    assert second["status"] == "rejected"


def test_unrelated_company_creates_a_separate_row(unique_company):
    # Deliberately a fresh random suffix, not unique_company + a fixed string --
    # appending text makes the new name a superstring of the old one, which the
    # substring-matching tier (correctly) treats as the same company.
    other_company = f"ZzzTestCorp{uuid.uuid4().hex[:8]}"
    first = job_tracker.upsert_application(unique_company, "Role A", "applied")
    second = job_tracker.upsert_application(other_company, "Role B", "applied")

    assert first["id"] != second["id"]
    assert job_tracker.get_application(unique_company)["role"] == "Role A"
    assert job_tracker.get_application(other_company)["role"] == "Role B"


def test_invalid_status_falls_back_to_other(unique_company):
    app = job_tracker.upsert_application(unique_company, "Role", "some_nonsense_status")
    assert app["status"] == "other"


def test_get_application_returns_none_for_unknown_company():
    assert job_tracker.get_application("DefinitelyNotARealCompanyXYZ999") is None


def test_email_dedup_tracking():
    email_id = f"zzz-test-{uuid.uuid4().hex[:8]}"
    assert job_tracker.is_email_processed(email_id) is False
    job_tracker.mark_email_processed(email_id)
    assert job_tracker.is_email_processed(email_id) is True


def test_find_interview_application_for_event_matches_by_substring(unique_company):
    job_tracker.upsert_application(unique_company, "Role", "interviewing")
    match = job_tracker.find_interview_application_for_event(f"{unique_company} Screening Round")
    assert match is not None
    assert match["company"] == unique_company


def test_find_interview_application_for_event_ignores_non_interviewing_status(unique_company):
    job_tracker.upsert_application(unique_company, "Role", "applied")
    match = job_tracker.find_interview_application_for_event(f"{unique_company} Screening Round")
    assert match is None


def test_find_interview_application_for_event_no_match():
    match = job_tracker.find_interview_application_for_event("Dentist appointment")
    assert match is None


def test_describe_job_status_mentions_interviews_and_pending_count(unique_company):
    interviewing_company = f"ZzzTestCorp{uuid.uuid4().hex[:8]}"
    job_tracker.upsert_application(unique_company, "Role A", "applied")
    job_tracker.upsert_application(interviewing_company, "Role B", "interviewing")

    description = job_tracker.describe_job_status()
    assert interviewing_company in description
    assert "pending" in description


def test_describe_job_status_excludes_rejections_when_nothing_else_pending(unique_company):
    """Rejections alone shouldn't produce a downbeat morning-briefing line --
    describe_job_status() is deliberately silent about rejections."""
    job_tracker.upsert_application(unique_company, "Role", "rejected")
    description = job_tracker.describe_job_status()
    assert unique_company not in description


def test_list_applications_filters_by_status(unique_company):
    other_company = f"ZzzTestCorp{uuid.uuid4().hex[:8]}"  # see note above -- must not be a substring/superstring of unique_company
    job_tracker.upsert_application(unique_company, "Role A", "rejected")
    job_tracker.upsert_application(other_company, "Role B", "applied")

    rejected = job_tracker.list_applications(status_filter="rejected")
    rejected_companies = {a["company"] for a in rejected}
    assert unique_company in rejected_companies
    assert other_company not in rejected_companies
