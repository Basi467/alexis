"""Recurring background calendar check -- one Windows Scheduled Task that runs
every CHECK_INTERVAL_MINUTES and speaks up only when an event is starting soon
and hasn't already been announced. Was 5 minutes; the user found that too
frequent and asked for hourly instead. deliver_calendar_check.py's
LOOKAHEAD_MINUTES is tied to this value -- see the comment there.
"""
import logging
import subprocess

from config import PYTHONW_EXECUTABLE, SCHEDULER_DIR
from scheduler.system_helpers import configure_task_settings

logger = logging.getLogger(__name__)

TASK_NAME = "Alexis_CalendarMonitor"
CHECK_INTERVAL_MINUTES = 60


def enable_calendar_monitoring() -> tuple[bool, str]:
    # No .bat file here on purpose -- see the same note in scheduler/watchdog.py.
    # This script takes no arguments, and a live window-polling test caught a
    # real, visible cmd.exe flash from the .bat's own console host even with
    # the task's Hidden setting on. Pointing /tr directly at pythonw.exe skips
    # cmd.exe entirely.
    script_path = SCHEDULER_DIR / "deliver_calendar_check.py"
    command = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{PYTHONW_EXECUTABLE}" "{script_path}"',
        "/sc", "minute", "/mo", str(CHECK_INTERVAL_MINUTES),
        "/f",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False, f"Failed to enable calendar monitoring: {result.stderr}"
    except Exception as e:
        logger.error("Failed to create calendar monitor task: %s", e)
        return False, f"Failed to enable calendar monitoring: {e}"

    configure_task_settings(TASK_NAME)
    return True, (
        f"I'll check your calendar every {CHECK_INTERVAL_MINUTES} minutes and give you "
        f"a heads-up before upcoming events."
    )


def disable_calendar_monitoring() -> tuple[bool, str]:
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, "Calendar monitoring turned off."
    except Exception as e:
        logger.error("Failed to disable calendar monitoring: %s", e)
        return False, f"Failed to turn off calendar monitoring: {e}"


def is_monitoring_enabled() -> bool:
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False
