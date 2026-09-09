"""Real mouse/keyboard control -- the "hard half" of computer control that
plain app-launching/volume/brightness control (systems/computer_control.py)
doesn't cover. Pairs with systems/vision.py: Alexis looks at the screen to
find something, then acts on it here.
"""
import logging

import pyautogui

logger = logging.getLogger(__name__)

# Slamming the mouse into a screen corner aborts whatever pyautogui call is in
# flight -- a physical emergency stop the user can always reach for, regardless
# of what Alexis is in the middle of doing.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

SUBMIT_LIKE_KEYS = {"enter", "return"}


def click_at(x: int, y: int) -> None:
    pyautogui.click(x, y)


def type_text(text: str) -> None:
    pyautogui.write(text, interval=0.02)


def press_key(key: str) -> bool:
    """key is a single pyautogui key name ('enter', 'tab', 'esc') or a hotkey
    combo like 'ctrl+c'. Returns False without pressing anything if any part
    isn't a key pyautogui recognizes, rather than silently doing nothing."""
    parts = [p.strip().lower() for p in key.split("+")]
    if not all(part in pyautogui.KEYBOARD_KEYS for part in parts):
        return False
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return True


def is_submit_like_key(key: str) -> bool:
    parts = [p.strip().lower() for p in key.split("+")]
    return any(part in SUBMIT_LIKE_KEYS for part in parts)


def scroll(amount: int) -> None:
    pyautogui.scroll(amount)
