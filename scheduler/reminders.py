"""General-purpose reminders, built the same way the daily alarm already works:
each reminder gets its own Windows Scheduled Task (precise, uses the OS's own
wake-from-sleep support) pointing directly at pythonw.exe with the reminder's
task_id as an argument -- no .bat file involved. A .bat was used here and for
the other background tasks originally because of concerns about
explorer.exe's argument-forwarding, but that concern was about explorer.exe
specifically, not about schtasks' own /tr handling multiple tokens (program +
arguments in one string), which works fine and was confirmed live via a
window-polling test: a .bat's own cmd.exe host was caught flashing a real,
visible window even with the task's Hidden setting on, and skipping cmd.exe
entirely (pointing /tr straight at pythonw.exe) eliminated it.
"""
import logging
import subprocess
import uuid
from datetime import datetime

from config import PYTHONW_EXECUTABLE, SCHEDULER_DIR
from scheduler import store
from scheduler.system_helpers import configure_task_settings

logger = logging.getLogger(__name__)

TASK_NAME_PREFIX = "Alexis_Reminder_"


def set_reminder(message: str, run_time: str, recurrence: str = "once") -> tuple[bool, str]:
    """run_time: an ISO-ish datetime string, e.g. '2026-08-30 15:05' or with a 'T'.
    recurrence: 'once' or 'daily'. For 'daily', only the time-of-day is used."""
    try:
        when = datetime.fromisoformat(run_time.replace("T", " "))
    except ValueError:
        return False, f"I couldn't understand the time '{run_time}'."

    if recurrence not in ("once", "daily"):
        recurrence = "once"

    task_id = uuid.uuid4().hex[:10]
    windows_task_name = f"{TASK_NAME_PREFIX}{task_id}"
    script_path = SCHEDULER_DIR / "deliver_reminder.py"

    command = [
        "schtasks", "/create",
        "/tn", windows_task_name,
        "/tr", f'"{PYTHONW_EXECUTABLE}" "{script_path}" {task_id}',
        "/st", when.strftime("%H:%M"),
        "/f",
    ]
    if recurrence == "once":
        command += ["/sc", "once", "/sd", when.strftime("%m/%d/%Y")]
    else:
        command += ["/sc", "daily"]

    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False, f"Failed to set reminder: {result.stderr}"
    except Exception as e:
        logger.error("Failed to create reminder task: %s", e)
        return False, f"Failed to set reminder: {e}"

    configure_task_settings(windows_task_name)
    store.add_task(task_id, message, when.isoformat(), recurrence, windows_task_name)

    when_phrase = when.strftime("%I:%M %p") if recurrence == "daily" else when.strftime("%I:%M %p on %B %d")
    return True, f"Reminder set: {message}, at {when_phrase}."


def list_reminders() -> list[dict]:
    return store.list_tasks()


def cancel_reminder(identifier: str) -> tuple[bool, str]:
    task = store.get_task(identifier) or store.find_task_by_message(identifier)
    if task is None:
        return False, f"I couldn't find a reminder matching '{identifier}'."

    delete_reminder_task(task)
    return True, f"Cancelled the reminder: {task['message']}."


def delete_reminder_task(task: dict) -> None:
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", task["windows_task_name"], "/f"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        logger.warning("Failed to delete scheduled task %r: %s", task["windows_task_name"], e)

    store.remove_task(task["task_id"])
