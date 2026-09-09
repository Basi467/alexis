"""Covers the parsing side of systems/email_intelligence.py's
extract_application_update() -- the regex that turns the LLM's reply into a
{company, role, status} dict, independent of whether the LLM itself gets the
extraction right (that's covered by live testing against real emails, not
something to re-verify with a mocked model on every run). ask_groq is
monkeypatched so these tests make no real API calls and cost nothing to run.
"""
import config
config.configure_logging()

import systems.email_intelligence as email_intelligence


def _fake_ask_groq(reply_text):
    def fake(prompt, model=None):
        return reply_text, None
    return fake


def _sample_email():
    return {"sender": "hr@example.com", "subject": "Interview", "snippet": "...", "body": "..."}


def test_well_formed_reply_with_role(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq(
        "company: TechCorp | role: Software Engineer | status: applied"
    ))
    result = email_intelligence.extract_application_update(_sample_email())
    assert result == {"company": "TechCorp", "role": "Software Engineer", "status": "applied"}


def test_well_formed_reply_with_no_role(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq(
        "company: BigCo | role: NONE | status: rejected"
    ))
    result = email_intelligence.extract_application_update(_sample_email())
    assert result == {"company": "BigCo", "role": None, "status": "rejected"}


def test_status_is_lowercased(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq(
        "company: StartupXYZ | role: PM | status: Offer"
    ))
    result = email_intelligence.extract_application_update(_sample_email())
    assert result["status"] == "offer"


def test_skip_response_returns_none(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq("SKIP"))
    assert email_intelligence.extract_application_update(_sample_email()) is None


def test_empty_response_returns_none(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq(""))
    assert email_intelligence.extract_application_update(_sample_email()) is None


def test_unparseable_response_returns_none(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq(
        "I'm not sure what company this is about."
    ))
    assert email_intelligence.extract_application_update(_sample_email()) is None


def test_empty_company_name_returns_none(monkeypatch):
    monkeypatch.setattr(email_intelligence, "ask_groq", _fake_ask_groq(
        "company:  | role: NONE | status: applied"
    ))
    assert email_intelligence.extract_application_update(_sample_email()) is None


def test_uses_body_over_snippet_when_available():
    email_with_body = {"sender": "x", "subject": "y", "snippet": "short", "body": "a much longer real body"}
    email_without_body = {"sender": "x", "subject": "y", "snippet": "short"}

    # _summarize_for_prompt is what the batch importance classifier uses --
    # confirm it prefers body over snippet, falling back when body is absent.
    summary_with_body = email_intelligence._summarize_for_prompt([email_with_body])
    summary_without_body = email_intelligence._summarize_for_prompt([email_without_body])
    assert "a much longer real body" in summary_with_body
    assert "short" in summary_without_body
