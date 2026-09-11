"""Lets Alexis actually look at the screen instead of only reasoning over text.
Captures a screenshot and hands it to a vision-capable model -- the main
conversation model (openai/gpt-oss-120b) is text-only, so this is a separate,
one-shot call to a different model rather than part of the normal agent loop.
"""
import base64
import io
import logging
import re

from PIL import Image, ImageGrab

from llm.groq_client import ask_vision

logger = logging.getLogger(__name__)

JPEG_QUALITY = 70  # keeps the upload small/fast without visibly degrading on-screen text


def _capture_screen() -> Image.Image | None:
    try:
        return ImageGrab.grab()
    except Exception as e:
        logger.error("Screen capture failed: %s", e)
        return None


def _encode_jpeg(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


HONESTY_INSTRUCTION = (
    "Only describe what you can actually and clearly see -- do not invent dialog "
    "boxes, popups, times, dates, or other specific details you aren't confident "
    "about. If text is too small to read reliably, say so instead of guessing at "
    "its content. It's fine to say you're not sure about something. Answer "
    "concisely, focused on what's actually relevant to the question -- don't "
    "produce an exhaustive itemized inventory of the whole screen unless asked to. "
)


def describe_screen(question: str) -> str | None:
    """Returns the vision model's answer about the current screen, or None if
    the screen couldn't be captured or the request failed."""
    image = _capture_screen()
    if image is None:
        return None

    answer, error = ask_vision(HONESTY_INSTRUCTION + question, _encode_jpeg(image))
    if error is not None:
        logger.warning("Vision request failed: %s", error)
        return None
    return answer


def locate_element_on_screen(description: str) -> tuple[int, int] | None:
    """Asks the vision model to pinpoint a described UI element and returns its
    center as real screen pixel coordinates, or None if it couldn't be found
    or the model's answer couldn't be parsed as coordinates. This is inherently
    less reliable than an accessibility-tree lookup would be -- qwen3.8-27b is a
    general vision model, not one trained specifically for GUI grounding -- so
    callers should treat a returned coordinate as a best guess, not a guarantee."""
    image = _capture_screen()
    if image is None:
        return None
    width, height = image.size

    prompt = (
        f'Find this element in the screenshot: "{description}". The image is '
        f"exactly {width} pixels wide and {height} pixels tall. Respond with ONLY "
        f'the pixel coordinates of its center as two integers separated by a '
        f'comma, like "842,213" -- no words, no explanation. If it is not visible, '
        f"respond with exactly: not_found"
    )
    answer, error = ask_vision(prompt, _encode_jpeg(image))
    if error is not None or not answer:
        return None

    answer = answer.strip().lower()
    if "not_found" in answer or "not found" in answer:
        logger.info("Vision model could not locate %r on screen.", description)
        return None

    match = re.search(r"(\d+)\s*,\s*(\d+)", answer)
    if not match:
        logger.warning("Vision model returned unparseable coordinates for %r: %r", description, answer)
        return None

    x, y = int(match.group(1)), int(match.group(2))
    if not (0 <= x < width and 0 <= y < height):
        logger.warning("Vision model returned out-of-bounds coordinates %d,%d for %r", x, y, description)
        return None
    return x, y
