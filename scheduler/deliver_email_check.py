import json
import os
import sys
import time
from pathlib import Path

# See deliver_alarm.py for why this bootstrap is needed before importing scheduler.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))

from scheduler.system_helpers import (
    log, wake_display, disable_lock_requirement, enable_lock_requirement,
    launch_main_if_not_running,
)


def _load_announced_ids() -> set:
    from config import EMAIL_CHECK_STATE_FILE
    if not os.path.exists(EMAIL_CHECK_STATE_FILE):
        return set()
    try:
        with open(EMAIL_CHECK_STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("announced_ids", []))
    except (json.JSONDecodeError, OSError) as e:
        log(f"Could not read email check state, starting fresh: {e}")
        return set()


def _save_announced_ids(ids: set) -> None:
    from config import EMAIL_CHECK_STATE_FILE
    try:
        with open(EMAIL_CHECK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"announced_ids": list(ids)}, f)
    except OSError as e:
        log(f"Failed to save email check state: {e}")


def main() -> None:
    log("Email check started")

    from systems.email_intelligence import check_for_important_emails, describe_important_emails
    from tts.edge_speaker import speak

    important = check_for_important_emails()
    if not important:
        log("No important emails found.")
        return

    announced = _load_announced_ids()
    new_important = [e for e in important if e["id"] not in announced]

    if not new_important:
        log("Important email(s) found, but already announced previously -- staying silent.")
        return

    log(f"Found {len(new_important)} new important email(s), announcing.")

    wake_display()
    disable_lock_requirement()
    time.sleep(8)
    wake_display()

    try:
        summary = describe_important_emails(new_important)
        message = f"You have {summary}."
        log(f"Speaking: {message}")
        speak(message)
        log("Speak completed successfully")
    except Exception as e:
        log(f"FATAL ERROR: {e}")
    finally:
        enable_lock_requirement()

    announced.update(e["id"] for e in new_important)
    _save_announced_ids(announced)

    launch_main_if_not_running()
    log("Email check finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # See deliver_alarm.py -- pythonw.exe has no console, so an uncaught
        # exception's default traceback (sys.stderr, which is None here) would
        # otherwise vanish with zero trace anywhere.
        log(f"UNCAUGHT ERROR: {e!r}")
        raise
