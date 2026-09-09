"""Covers memory/episodic.py -- the searchable conversation-history log that
lets Alexis answer "what did we talk about yesterday" or "did I mention X
before". Operates on the real shared SQLite/FAISS database (no dependency-
injection seam exists for a test DB without a larger refactor), so every test
uses obviously-fake ZZZTEST-prefixed text and an autouse fixture that deletes
matching rows afterward.
"""
import uuid
from datetime import datetime, timedelta

import pytest

import config
config.configure_logging()

from memory import episodic


@pytest.fixture(autouse=True)
def _cleanup_test_rows():
    yield
    episodic._conn.execute("DELETE FROM conversation_log WHERE user_text LIKE 'ZZZTEST%'")
    episodic._conn.commit()
    episodic._load_index()


def _marker():
    return f"ZZZTEST{uuid.uuid4().hex[:8]}"


def test_logged_exchange_is_findable_by_semantic_query():
    marker = _marker()
    episodic.log_exchange(f"{marker} what is the capital of France", f"{marker} The capital of France is Paris.")

    results = episodic.search_conversation_history(query=f"{marker} country capital city")
    assert any(marker in r["user_text"] for r in results)


def test_unrelated_query_does_not_match():
    marker = _marker()
    episodic.log_exchange(f"{marker} what is the capital of France", f"{marker} The capital of France is Paris.")

    results = episodic.search_conversation_history(query="completely unrelated quantum physics nuclear reactor")
    assert not any(marker in r["user_text"] for r in results)


def test_no_query_returns_recent_exchanges_most_recent_first():
    marker = _marker()
    episodic.log_exchange(f"{marker} first thing", f"{marker} first reply")
    episodic.log_exchange(f"{marker} second thing", f"{marker} second reply")

    results = episodic.search_conversation_history(max_results=50)
    marker_results = [r for r in results if marker in r["user_text"]]
    assert len(marker_results) == 2
    assert marker_results[0]["user_text"] == f"{marker} second thing"
    assert marker_results[1]["user_text"] == f"{marker} first thing"


def test_date_range_filters_out_of_range_exchanges():
    marker = _marker()
    episodic.log_exchange(f"{marker} todays exchange", f"{marker} reply")

    today = datetime.now().date().isoformat()
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

    in_range = episodic.search_conversation_history(start_date=today, end_date=today, max_results=50)
    assert any(marker in r["user_text"] for r in in_range)

    out_of_range = episodic.search_conversation_history(start_date=yesterday, end_date=yesterday, max_results=50)
    assert not any(marker in r["user_text"] for r in out_of_range)


def test_query_and_date_range_combined():
    marker = _marker()
    episodic.log_exchange(f"{marker} tell me about Rust programming", f"{marker} Rust is a systems language.")

    today = datetime.now().date().isoformat()
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

    matches_today = episodic.search_conversation_history(query=f"{marker} programming language", start_date=today, end_date=today)
    assert any(marker in r["user_text"] for r in matches_today)

    matches_yesterday = episodic.search_conversation_history(query=f"{marker} programming language", start_date=yesterday, end_date=yesterday)
    assert not any(marker in r["user_text"] for r in matches_yesterday)


def test_empty_user_text_is_not_logged():
    before = episodic._conn.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]
    episodic.log_exchange("", "some reply")
    episodic.log_exchange("   ", "some reply")
    after = episodic._conn.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]
    assert before == after


def test_describe_conversation_history_formatting():
    marker = _marker()
    results = [{"user_text": f"{marker} hello", "assistant_text": f"{marker} hi there", "timestamp": "2026-09-03T12:30:00"}]
    description = episodic.describe_conversation_history(results)
    assert "2026-09-03 12:30" in description
    assert f"{marker} hello" in description
    assert f"{marker} hi there" in description


def test_describe_conversation_history_empty():
    assert episodic.describe_conversation_history([]) == ""
