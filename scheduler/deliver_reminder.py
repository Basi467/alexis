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


def main() -> None:
    if len(sys.argv) < 2:
        log("deliver_reminder.py called with no task_id, aborting")
        return

    task_id = sys.argv[1]
    log(f"Reminder script started for task_id={task_id}")

    from scheduler import store, reminders
    from tts.edge_speaker import speak

    task = store.get_task(task_id)
    if task is None:
        log(f"No stored reminder found for task_id={task_id}, aborting")
        return

    wake_display()
    disable_lock_requirement()
    time.sleep(8)
    wake_display()

    try:
        message = f"Reminder: {task['message']}"
        log(f"Speaking: {message}")
        speak(message)
        log("Speak completed successfully")
    except Exception as e:
        log(f"FATAL ERROR: {e}")
    finally:
        enable_lock_requirement()

    if task["recurrence"] == "once":
        log(f"One-time reminder fired, cleaning up task_id={task_id}")
        reminders.delete_reminder_task(task)

    launch_main_if_not_running()
    log("Reminder script finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # See deliver_alarm.py -- pythonw.exe has no console, so an uncaught
        # exception's default traceback (sys.stderr, which is None here) would
        # otherwise vanish with zero trace anywhere.
        log(f"UNCAUGHT ERROR: {e!r}")
        raise
