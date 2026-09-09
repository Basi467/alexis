import json
import logging
import os
from datetime import datetime

from config import TASKS_FILE

logger = logging.getLogger(__name__)


def _load_tasks() -> list[dict]:
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Tasks file corrupted: %s", e)
        return []


def _save_tasks(tasks: list[dict]) -> None:
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)
    except OSError as e:
        logger.error("Failed to save tasks: %s", e)


def add_task(task_id: str, message: str, run_time: str, recurrence: str, windows_task_name: str) -> None:
    tasks = _load_tasks()
    tasks.append({
        "task_id": task_id,
        "message": message,
        "run_time": run_time,  # ISO format, e.g. "2026-08-30T15:05:00"
        "recurrence": recurrence,  # "once" or "daily"
        "windows_task_name": windows_task_name,
        "created": datetime.now().isoformat(),
    })
    _save_tasks(tasks)


def list_tasks() -> list[dict]:
    return _load_tasks()


def get_task(task_id: str) -> dict | None:
    for task in _load_tasks():
        if task["task_id"] == task_id:
            return task
    return None


def find_task_by_message(query: str) -> dict | None:
    """Substring match, either direction -- so the user can cancel a reminder by
    roughly what it says ("cancel the oven reminder") without knowing its internal id."""
    query_lower = query.lower()
    tasks = _load_tasks()

    for task in tasks:
        if query_lower in task["message"].lower() or task["message"].lower() in query_lower:
            return task
    return None


def remove_task(task_id: str) -> None:
    tasks = _load_tasks()
    tasks = [t for t in tasks if t["task_id"] != task_id]
    _save_tasks(tasks)
