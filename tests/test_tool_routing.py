"""Covers _classify_relevant_tools in llm/router.py -- added after confirming
live that sending all ~51 tool schemas (~5500 tokens) on every single step of
a multi-step tool-calling chain was the direct cause of repeatedly hitting
Groq's daily rate limit. This narrows the tool list sent to the model based on
a cheap category classification instead. The critical property tested here
isn't "does it guess the right category" (that's inherently fuzzy) -- it's
that failure modes (empty reply, unparseable reply, an explicit NONE) never
silently make a genuinely needed tool unavailable; they fall back to the full
catalog instead, since that's a token-cost problem, not a correctness one,
while an actually-missing tool would break the request outright.
"""
import pytest

import config
config.configure_logging()

import llm.router as router


def test_matched_category_includes_its_tools_and_always_available_ones(monkeypatch):
    monkeypatch.setattr(router, "ask_groq", lambda *a, **k: ("calendar", None))
    result = router._classify_relevant_tools("what's on my calendar today")
    names = {t["function"]["name"] for t in result}

    assert "get_calendar_events" in names
    assert "create_calendar_event" in names
    for always_on in router.ALWAYS_AVAILABLE_TOOL_NAMES:
        assert always_on in names
    # Something from an unrelated category should NOT be included.
    assert "play_spotify" not in names
    assert len(result) < len(router.TOOLS)


def test_multiple_categories_are_unioned(monkeypatch):
    monkeypatch.setattr(router, "ask_groq", lambda *a, **k: ("calendar,files_and_documents", None))
    result = router._classify_relevant_tools("check my calendar and find my resume")
    names = {t["function"]["name"] for t in result}

    assert "get_calendar_events" in names
    assert "find_file_by_name" in names
    assert "play_spotify" not in names


def test_explicit_none_returns_only_always_available_tools(monkeypatch):
    monkeypatch.setattr(router, "ask_groq", lambda *a, **k: ("NONE", None))
    result = router._classify_relevant_tools("how are you doing today")
    names = {t["function"]["name"] for t in result}

    assert names == router.ALWAYS_AVAILABLE_TOOL_NAMES


def test_empty_reply_falls_back_to_full_tool_list(monkeypatch):
    monkeypatch.setattr(router, "ask_groq", lambda *a, **k: ("", None))
    result = router._classify_relevant_tools("anything")
    assert result == router.TOOLS


def test_unparseable_reply_falls_back_to_full_tool_list(monkeypatch):
    monkeypatch.setattr(router, "ask_groq", lambda *a, **k: ("garbage nonsense response", None))
    result = router._classify_relevant_tools("anything")
    assert result == router.TOOLS


def test_rate_limit_message_falls_back_to_full_tool_list(monkeypatch):
    from llm.groq_client import RATE_LIMIT_MESSAGE
    monkeypatch.setattr(router, "ask_groq", lambda *a, **k: (RATE_LIMIT_MESSAGE, None))
    result = router._classify_relevant_tools("anything")
    assert result == router.TOOLS


def test_every_tool_is_reachable_through_some_category_or_always_available():
    """Guards against a tool silently becoming permanently unreachable (never
    included regardless of classification) because it was added to ALL_TOOLS/
    TOOLS but forgotten in TOOL_CATEGORIES."""
    categorized = {name for names in router.TOOL_CATEGORIES.values() for name in names}
    covered = categorized | router.ALWAYS_AVAILABLE_TOOL_NAMES
    all_tool_names = {t["function"]["name"] for t in router.TOOLS}

    missing = all_tool_names - covered
    assert not missing, f"Tools not reachable through any category: {missing}"
