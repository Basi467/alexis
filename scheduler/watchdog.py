"""Recovers from main.py dying in a way no in-process try/except can catch --
a hard crash, a segfault in a C extension, the process getting killed. main.py
already catches ordinary exceptions inside its own run loop and keeps going,
but that's no help if the process itself is gone. This is a Windows Scheduled
Task that runs every CHECK_INTERVAL_MINUTES and relaunches main.py if it's not
running -- the same launch_main_if_not_running() the email/calendar monitors
already use as a side effect, just checked on its own frequent schedule
instead of only incidentally every 30-60 minutes.
"""
import logging
import subprocess

from config import PYTHONW_EXECUTABLE, SCHEDULER_DIR
from scheduler.system_helpers import configure_task_settings

logger = logging.getLogger(__name__)

TASK_NAME = "Alexis_Watchdog"
CHECK_INTERVAL_MINUTES = 5


def enable_watchdog() -> tuple[bool, str]:
    # No .bat file here on purpose -- this script takes no arguments, so the
    # .bat added nothing but an extra cmd.exe host to launch. That mattered:
    # even with the task's own Hidden setting, a live test caught a real,
    # visible cmd.exe window flashing during an actual scheduled run (Hidden
    # apparently doesn't fully suppress a .bat's own console host on this
    # system). Pointing /tr directly at pythonw.exe + the script path skips
    # cmd.exe entirely, confirmed via the same live window-polling test to
    # produce zero visible windows.
    script_path = SCHEDULER_DIR / "deliver_watchdog_check.py"
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
            return False, f"Failed to enable the watchdog: {result.stderr}"
    except Exception as e:
        logger.error("Failed to create watchdog task: %s", e)
        return False, f"Failed to enable the watchdog: {e}"

    configure_task_settings(TASK_NAME)
    return True, f"Watchdog enabled -- checks every {CHECK_INTERVAL_MINUTES} minutes and relaunches Alexis if it's not running."


def disable_watchdog() -> tuple[bool, str]:
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, "Watchdog disabled."
    except Exception as e:
        logger.error("Failed to disable watchdog: %s", e)
        return False, f"Failed to disable the watchdog: {e}"


def is_watchdog_enabled() -> bool:
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False
