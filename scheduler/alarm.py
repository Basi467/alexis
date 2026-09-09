import logging
import subprocess

from config import PYTHONW_EXECUTABLE, SCHEDULER_DIR
from scheduler.system_helpers import configure_task_settings

logger = logging.getLogger(__name__)

TASK_NAME = "AlexisDailyAlarm"


def set_daily_alarm(time_str: str) -> tuple[bool, str]:
    remove_daily_alarm()

    # No .bat file here on purpose -- see the same note in scheduler/watchdog.py.
    # deliver_alarm.py takes no arguments, and a live window-polling test
    # caught a real, visible cmd.exe flash from a .bat's own console host even
    # with the task's Hidden setting on. Pointing /tr directly at pythonw.exe
    # skips cmd.exe entirely.
    script_path = SCHEDULER_DIR / "deliver_alarm.py"
    command = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{PYTHONW_EXECUTABLE}" "{script_path}"',
        "/sc", "daily",
        "/st", time_str,
        "/f"
    ]

    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False, f"Failed to set alarm: {result.stderr}"

        configure_task_settings(TASK_NAME)
        return True, f"Alarm set for {time_str} every day."

    except Exception as e:
        logger.error("Failed to set alarm: %s", e)
        return False, f"Failed to set alarm: {e}"


def remove_daily_alarm() -> None:
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def get_alarm_status() -> str | None:
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None
