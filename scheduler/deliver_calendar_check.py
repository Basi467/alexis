import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# See deliver_alarm.py for why this bootstrap is needed before importing scheduler.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))

from scheduler.system_helpers import (
    log, wake_display, disable_lock_requirement, enable_lock_requirement,
    launch_main_if_not_running,
)

# How far ahead to look for an event worth announcing. Must be >= the poll
# interval (calendar_monitor.CHECK_INTERVAL_MINUTES, now 60) or an event could
# fall entirely between two checks and never get announced at all -- e.g. an
# event 45 minutes out at check time wouldn't be caught by a 15-minute window,
# and by the next hourly check it would already be in the past. 75 gives a
# margin over the 60-minute interval so timing jitter can't create that gap;
# the tradeoff versus the old 5-min/15-min setup is less precise lead time
# (anywhere from a few minutes to just over an hour before the event, instead
# of a steady 10-15) in exchange for far fewer background checks.
LOOKAHEAD_MINUTES = 75


def _load_announced_ids() -> set:
    from config import CALENDAR_CHECK_STATE_FILE
    if not os.path.exists(CALENDAR_CHECK_STATE_FILE):
        return set()
    try:
        with open(CALENDAR_CHECK_STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("announced_ids", []))
    except (json.JSONDecodeError, OSError) as e:
        log(f"Could not read calendar check state, starting fresh: {e}")
        return set()


def _save_announced_ids(ids: set) -> None:
    from config import CALENDAR_CHECK_STATE_FILE
    try:
        with open(CALENDAR_CHECK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"announced_ids": list(ids)}, f)
    except OSError as e:
        log(f"Failed to save calendar check state: {e}")


def _build_interview_heads_up(matched_app: dict) -> str:
    """Tailored heads-up for a tracked interview -- names the company, and
    tries to add a one-sentence company blurb pulled from a live web search.
    Falls back to just the plain company-name heads-up if the search fails or
    turns up nothing usable -- a missing blurb must never block the actual
    reminder from going out."""
    company = matched_app["company"]
    message = f"Heads up, your {company} interview is coming up soon. Good luck!"

    try:
        from systems.web_research import search_and_read
        from llm.groq_client import ask_groq, CLASSIFICATION_MODEL

        result = search_and_read(f"{company} company")
        if result:
            prompt = (
                f"In one short spoken sentence, summarize what this company does, "
                f"based on this text from {result['title']}:\n\n{result['text'][:1500]}\n\n"
                f"No markdown, no preamble. If this text doesn't actually describe a "
                f"real company, respond with exactly: SKIP"
            )
            blurb, _ = ask_groq(prompt, model=CLASSIFICATION_MODEL)
            if blurb and blurb.strip() and blurb.strip().upper() != "SKIP":
                message += f" Quick note: {blurb.strip()}"
    except Exception as e:
        log(f"Interview company lookup failed: {e}")

    return message


def _build_heads_up_message(new_upcoming: list[dict]) -> str:
    """Generic "you have X coming up" for ordinary events, but tailored (names
    the company, tries for a quick blurb) if any of the events matches a
    tracked interview -- the whole point of cross-referencing the calendar
    against the job tracker instead of treating every event identically."""
    from memory.job_tracker import find_interview_application_for_event

    matched_app = None
    matched_event = None
    for e in new_upcoming:
        app = find_interview_application_for_event(e["summary"])
        if app:
            matched_app = app
            matched_event = e
            break

    if matched_app is None:
        titles = ", ".join(e["summary"] for e in new_upcoming)
        return f"Heads up, you have {titles} coming up soon."

    message = _build_interview_heads_up(matched_app)
    other_titles = [e["summary"] for e in new_upcoming if e is not matched_event]
    if other_titles:
        message += f" Also coming up: {', '.join(other_titles)}."
    return message


def main() -> None:
    log("Calendar check started")

    from systems.calendar_client import list_events
    from tts.edge_speaker import speak

    now = datetime.now().astimezone()
    today = now.strftime("%Y-%m-%d")
    events = list_events(today, days=1, max_results=20)

    upcoming = []
    for e in events:
        try:
            start = datetime.fromisoformat(e["start"])
        except (ValueError, TypeError):
            continue  # all-day events use a bare date, not a datetime -- skip those
        minutes_until = (start - now).total_seconds() / 60
        if 0 <= minutes_until <= LOOKAHEAD_MINUTES:
            upcoming.append(e)

    if not upcoming:
        log("No upcoming events within the lookahead window.")
        return

    announced = _load_announced_ids()
    new_upcoming = [e for e in upcoming if e["id"] not in announced]

    if not new_upcoming:
        log("Upcoming event(s) found, but already announced -- staying silent.")
        return

    log(f"Found {len(new_upcoming)} new upcoming event(s), announcing.")

    wake_display()
    disable_lock_requirement()
    time.sleep(8)
    wake_display()

    try:
        message = _build_heads_up_message(new_upcoming)
        log(f"Speaking: {message}")
        speak(message)
        log("Speak completed successfully")
    except Exception as e:
        log(f"FATAL ERROR: {e}")
    finally:
        enable_lock_requirement()

    announced.update(e["id"] for e in new_upcoming)
    _save_announced_ids(announced)

    launch_main_if_not_running()
    log("Calendar check finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # See deliver_alarm.py -- pythonw.exe has no console, so an uncaught
        # exception's default traceback (sys.stderr, which is None here) would
        # otherwise vanish with zero trace anywhere.
        log(f"UNCAUGHT ERROR: {e!r}")
        raise
