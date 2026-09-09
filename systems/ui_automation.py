"""UI-Automation-based element finding, preferred over vision-guessed pixel
coordinates whenever a window exposes proper accessible control names.

Confirmed via live testing that vision-only coordinate guessing (see
systems/vision.py's locate_element_on_screen) is not reliable even for
something as simple as Calculator's buttons -- a real test clicking 7, +, 3, =
landed on a result of 2, not 10, because the vision model's guessed pixel for
"the plus button" fell outside the actual button (in one case outside the
window entirely). UI Automation reads the app's own accessibility tree for
exact bounding boxes instead of guessing from a screenshot, so it's tried
first; vision stays as the fallback for apps that don't expose proper control
names (games, canvases, custom-rendered UI).
"""
import logging
import re

import win32gui
from pywinauto import Desktop

from llm.groq_client import ask_groq, CLASSIFICATION_MODEL

logger = logging.getLogger(__name__)

CLICKABLE_CONTROL_TYPES = {
    "Button", "MenuItem", "ListItem", "TabItem", "CheckBox", "RadioButton",
    "ComboBox", "Hyperlink", "Edit", "Text",
}
MAX_CANDIDATES = 60  # keeps the classification prompt small and fast


def _foreground_uia_window():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        return Desktop(backend="uia").window(handle=hwnd)
    except Exception as e:
        logger.warning("Could not attach UI Automation to foreground window: %s", e)
        return None


def find_control_center(description: str) -> tuple[int, int] | None:
    """Returns the screen-pixel center of the foreground window's control that
    best matches description, or None if UI Automation found no window, no
    candidates, or no confident match -- callers should fall back to
    vision-based coordinate guessing in that case."""
    window = _foreground_uia_window()
    if window is None:
        return None

    try:
        controls = window.descendants()
    except Exception as e:
        logger.warning("Failed to enumerate UI Automation descendants: %s", e)
        return None

    candidates = []
    for ctrl in controls:
        try:
            if ctrl.element_info.control_type not in CLICKABLE_CONTROL_TYPES:
                continue
            if not ctrl.is_visible():
                continue
            name = ctrl.window_text()
            if not name or not name.strip():
                continue
            candidates.append((name, ctrl))
        except Exception:
            continue
        if len(candidates) >= MAX_CANDIDATES:
            break

    if not candidates:
        return None

    listing = "\n".join(f"{i}: {name}" for i, (name, _) in enumerate(candidates))
    prompt = (
        f"Here is a numbered list of clickable UI elements in the current window:\n{listing}\n\n"
        f'Which number best matches this description: "{description}"? '
        f"Respond with ONLY the number, or the word none if nothing reasonably matches."
    )
    answer, _ = ask_groq(prompt, model=CLASSIFICATION_MODEL)
    answer = answer.strip().lower()
    if "none" in answer:
        logger.info("UI Automation found no confident match for %r among %d candidates.", description, len(candidates))
        return None

    match = re.search(r"\d+", answer)
    if not match:
        return None
    index = int(match.group())
    if index >= len(candidates):
        return None

    _, control = candidates[index]
    try:
        rect = control.rectangle()
        return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
    except Exception as e:
        logger.warning("Failed to get control rectangle: %s", e)
        return None
