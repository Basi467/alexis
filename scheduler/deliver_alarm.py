import sys
import time
from pathlib import Path

# Task Scheduler launches this script directly by path, so Python sets sys.path[0]
# to this script's own directory (scheduler/), not the project root -- meaning
# `scheduler` itself isn't importable as a package yet without this. system_helpers
# also fixes sys.path, but only once it can be imported, which needs this first.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))

from scheduler.system_helpers import (
    log, wake_display, disable_lock_requirement, enable_lock_requirement,
    launch_main_if_not_running, butlerify,
)

BUTLER_STYLE_HINT = (
    "You are Alexis, acting as a warm, witty personal butler waking your employer up "
    "for the day. Rephrase the following as a short, fun, characterful wake-up "
    "greeting -- polished and a little playful, address them as 'sir', 2 to 4 sentences."
)


def speak_alarm() -> None:
    from systems.datetimeandweather_info import get_datetime_info, get_time_based_greeting, get_weather
    from systems.email_intelligence import check_for_important_emails, describe_important_emails
    from systems.gmail_client import is_configured as is_gmail_configured
    from systems.calendar_client import list_events, describe_events, is_configured as is_calendar_configured
    from memory.job_tracker import describe_job_status
    from tts.edge_speaker import speak

    greeting = get_time_based_greeting()

    try:
        datetime_info = get_datetime_info()
    except Exception as e:
        log(f"get_datetime_info failed: {e}")
        datetime_info = ""

    try:
        weather_info = get_weather()
    except Exception as e:
        log(f"get_weather failed: {e}")
        weather_info = ""

    email_info = ""
    if is_gmail_configured():
        try:
            important = check_for_important_emails()
            if important:
                email_info = f"Also, you have {describe_important_emails(important)}."
        except Exception as e:
            log(f"email check failed: {e}")

    calendar_info = ""
    if is_calendar_configured():
        try:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            events = list_events(today, days=1)
            if events:
                calendar_info = f"On your calendar today: {describe_events(events)}."
        except Exception as e:
            log(f"calendar check failed: {e}")

    job_status_info = ""
    try:
        job_status_info = describe_job_status()
    except Exception as e:
        log(f"job status check failed: {e}")

    plain_message = f"{greeting} {datetime_info} {weather_info} {email_info} {calendar_info} {job_status_info}".strip()
    if not plain_message or plain_message == greeting:
        plain_message = f"{greeting} Time to wake up."

    message = butlerify(plain_message, BUTLER_STYLE_HINT)

    log(f"Speaking: {message}")
    # Fades in over 10s instead of starting at full volume -- an instant full-
    # volume voice right as the user wakes up was reported as startling, the
    # same complaint that led to the wake-up song's own fade-in.
    speak(message, fade_in_seconds=10.0)
    log("Speak completed successfully")


def main() -> None:
    log("Alarm script started")
    wake_display()
    disable_lock_requirement()
    time.sleep(8)
    wake_display()  # in case the display timed out again during the settle delay

    try:
        speak_alarm()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
    finally:
        enable_lock_requirement()

    launch_main_if_not_running(extra_args=["--play-wake-song"])
    log("Alarm script finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Runs under pythonw.exe (no console), so an uncaught exception's default
        # traceback would otherwise go to sys.stderr -- which is None here -- and
        # vanish with zero trace anywhere. log() writes straight to a file, so
        # this is the only thing that keeps a real failure from being invisible.
        log(f"UNCAUGHT ERROR: {e!r}")
        raise
