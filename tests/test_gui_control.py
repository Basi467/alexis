"""Covers systems/gui_control.py's pure logic -- key-name validation and the
submit-like-key classification that drives whether press_key needs
confirmation. Doesn't touch the real mouse/keyboard (that's covered by live
testing against Calculator, not something an automated suite should do)."""
from systems.gui_control import is_submit_like_key, press_key


def test_is_submit_like_key_matches_enter_and_return():
    assert is_submit_like_key("enter") is True
    assert is_submit_like_key("return") is True
    assert is_submit_like_key("ctrl+enter") is True
    assert is_submit_like_key("ENTER") is True


def test_is_submit_like_key_rejects_navigation_keys():
    assert is_submit_like_key("tab") is False
    assert is_submit_like_key("esc") is False
    assert is_submit_like_key("ctrl+c") is False
    assert is_submit_like_key("up") is False


def test_press_key_rejects_unrecognized_key_names():
    assert press_key("not_a_real_key_name_xyz") is False
