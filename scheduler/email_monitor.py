"""Recurring background email check -- one Windows Scheduled Task (not one per
check, unlike reminders) that runs every CHECK_INTERVAL_MINUTES and stays silent
unless it finds something new and important.
"""
import logging
import subprocess

from config import PYTHONW_EXECUTABLE, SCHEDULER_DIR
from scheduler.system_helpers import configure_task_settings

logger = logging.getLogger(__name__)

TASK_NAME = "Alexis_EmailMonitor"
CHECK_INTERVAL_MINUTES = 30


def enable_email_monitoring() -> tuple[bool, str]:
    # No .bat file here on purpose -- see the same note in scheduler/watchdog.py.
    # This script takes no arguments, and a live window-polling test caught a
    # real, visible cmd.exe flash from the .bat's own console host even with
    # the task's Hidden setting on. Pointing /tr directly at pythonw.exe skips
    # cmd.exe entirely.
    script_path = SCHEDULER_DIR / "deliver_email_check.py"
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
            return False, f"Failed to enable email monitoring: {result.stderr}"
    except Exception as e:
        logger.error("Failed to create email monitor task: %s", e)
        return False, f"Failed to enable email monitoring: {e}"

    configure_task_settings(TASK_NAME)
    return True, (
        f"I'll check your email every {CHECK_INTERVAL_MINUTES} minutes and let you "
        f"know if anything important comes in."
    )


def disable_email_monitoring() -> tuple[bool, str]:
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, "Email monitoring turned off."
    except Exception as e:
        logger.error("Failed to disable email monitoring: %s", e)
        return False, f"Failed to turn off email monitoring: {e}"


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
