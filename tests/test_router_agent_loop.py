"""Covers the agent loop's confirmation/resumption logic in llm/router.py --
the most complex and most recently bug-fixed part of the app. Two real bugs
were found here through live manual testing before these tests existed:

1. click_on_screen/type_text/press_key/scroll_screen used to mark themselves
   as a "direct final reply", which stopped the whole turn after just one
   click -- a multi-click task could never complete via a real voice request.
2. Confirming a gated action (e.g. a click) used to execute just that one
   tool and return, discarding the rest of the original multi-step plan.

These tests formalize the manual/scripted verification done at the time, so a
future change can't silently reintroduce either bug. chat_completion is
monkeypatched with a scripted sequence of fake tool calls -- no real Groq
calls, no real mouse/keyboard/screen access.
"""
import json

import pytest

import config
config.configure_logging()

import llm.router as router


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id, name, args_dict):
        self.id = call_id
        self.function = FakeFunction(name, json.dumps(args_dict))


class FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _scripted_chat_completion(script):
    """Returns a chat_completion-shaped callable that pops one scripted
    message per call, ignoring its real arguments (messages/tools/model)."""
    def fake(messages, tools=None, model=None):
        return script.pop(0), None
    return fake


@pytest.fixture(autouse=True)
def _patch_gui_actions(monkeypatch):
    """Every test in this file stubs the actual mouse/UI-Automation/vision
    calls so nothing touches the real screen -- these tests are about the
    router's control flow, not whether a click lands correctly (that's
    covered by live/manual testing against Calculator, not something an
    automated suite can do without real hardware)."""
    calls = []
    monkeypatch.setattr(router, "click_at", lambda x, y: calls.append(("click_at", x, y)))
    monkeypatch.setattr(router, "find_control_center", lambda desc: calls.append(("find_control_center", desc)) or (100, 100))
    return calls


def test_multi_click_chain_completes_with_a_single_confirmation(_patch_gui_actions, monkeypatch):
    """Bug 1 + Bug 2 combined: a plan with 4 chained click_on_screen calls
    should complete every step, asking for confirmation only once (not once
    per click), and should NOT stop after just the first click."""
    script = [
        FakeMessage(None, [FakeToolCall("c1", "click_on_screen", {"description": "the 7 button"})]),
        FakeMessage(None, [FakeToolCall("c2", "click_on_screen", {"description": "the plus button"})]),
        FakeMessage(None, [FakeToolCall("c3", "click_on_screen", {"description": "the 3 button"})]),
        FakeMessage(None, [FakeToolCall("c4", "click_on_screen", {"description": "the equals button"})]),
        FakeMessage("The result is 10.", []),
    ]
    monkeypatch.setattr(router, "chat_completion", _scripted_chat_completion(script))

    history = []
    result = router.route("click 7 plus 3 equals on the calculator", history)
    assert result["pending_confirmation"] is not None
    assert "7 button" in result["text"]

    confirmations = 0
    pending = result["pending_confirmation"]
    while pending is not None:
        confirmations += 1
        result = router.route("yes", history, pending)
        pending = result["pending_confirmation"]

    assert confirmations == 1, "should only need one confirmation for the whole chain, not one per click"
    assert result["action"] == "reply"
    assert result["text"] == "The result is 10."

    click_calls = [c for c in _patch_gui_actions if c[0] == "click_at"]
    assert len(click_calls) == 4, "all 4 clicks in the plan should have executed, not just the first"


def test_normal_single_shot_confirmation_is_unaffected(monkeypatch):
    """A plain, non-GUI confirmation-required tool (set_daily_alarm) must
    behave exactly as before this refactor: one question, one confirm, the
    tool's own result returned immediately -- no attempt to continue looping."""
    script = [FakeMessage(None, [FakeToolCall("c1", "set_daily_alarm", {"time": "07:00"})])]
    monkeypatch.setattr(router, "chat_completion", _scripted_chat_completion(script))
    monkeypatch.setattr(router, "set_daily_alarm", lambda t: (True, f"Alarm set for {t} every day."))

    result = router.route("set my alarm for 7am", [])
    assert result["pending_confirmation"] is not None

    result = router.route("yes", [], result["pending_confirmation"])
    assert result["action"] == "reply"
    assert result["text"] == "Alarm set for 07:00 every day."
    assert result["pending_confirmation"] is None


def test_gui_confirmation_does_not_leak_into_unrelated_tools(_patch_gui_actions, monkeypatch):
    """Confirming one click must not silently approve a later, unrelated
    confirmation-required tool (e.g. open_website) that shows up in the same
    chain -- only the click_on_screen/type_text/submit-key family should be
    covered by a single approval."""
    script = [
        FakeMessage(None, [FakeToolCall("c1", "click_on_screen", {"description": "the search button"})]),
        FakeMessage(None, [FakeToolCall("c2", "open_website", {"site": "youtube.com"})]),
    ]
    monkeypatch.setattr(router, "chat_completion", _scripted_chat_completion(script))

    history = []
    result = router.route("click search then open youtube", history)
    assert result["pending_confirmation"] is not None

    result = router.route("yes", history, result["pending_confirmation"])
    assert result["pending_confirmation"] is not None, "open_website should still need its own confirmation"
    assert "youtube.com" in result["text"]


def test_declining_a_confirmation_stops_the_plan(monkeypatch):
    script = [FakeMessage(None, [FakeToolCall("c1", "restart_computer", {})])]
    monkeypatch.setattr(router, "chat_completion", _scripted_chat_completion(script))

    result = router.route("restart the computer", [])
    assert result["pending_confirmation"] is not None

    result = router.route("no don't", [], result["pending_confirmation"])
    assert result["action"] == "reply"
    assert result["text"] == "Okay, I won't do that."
    assert result["pending_confirmation"] is None


def test_press_key_only_confirms_for_submit_like_keys():
    assert router._requires_confirmation({"name": "press_key", "arguments": {"key": "enter"}}) is True
    assert router._requires_confirmation({"name": "press_key", "arguments": {"key": "ctrl+enter"}}) is True
    assert router._requires_confirmation({"name": "press_key", "arguments": {"key": "tab"}}) is False
    assert router._requires_confirmation({"name": "press_key", "arguments": {"key": "escape"}}) is False


def test_is_gui_action_classification():
    assert router._is_gui_action({"name": "click_on_screen", "arguments": {"description": "x"}}) is True
    assert router._is_gui_action({"name": "type_text", "arguments": {"text": "x"}}) is True
    assert router._is_gui_action({"name": "press_key", "arguments": {"key": "enter"}}) is True
    assert router._is_gui_action({"name": "press_key", "arguments": {"key": "tab"}}) is False
    assert router._is_gui_action({"name": "open_website", "arguments": {"site": "x"}}) is False
