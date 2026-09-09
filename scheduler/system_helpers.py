"""Shared logic for standalone scripts launched by Windows Task Scheduler (the daily
alarm and reminders) -- both need to log to the same place, wake the display, and
temporarily bypass the lock screen so they can actually be heard, then hand off to
main.py. Kept in one place so a fix (like the UTF-8 logging bug) only has to happen
once."""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / "scheduler" / "alarm_log.txt"

# Scripts launched directly by Task Scheduler run from a directory that may not have
# the project root on sys.path yet.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# These entry scripts now run under pythonw.exe (no console at all -- see
# config.PYTHONW_EXECUTABLE), so ordinary logger.info/warning/error calls from
# anywhere in the app (router.py, groq_client.py, etc.) would otherwise go
# nowhere during a background run. Routing them into the same file as the
# dedicated log() below keeps everything in one readable, timestamped place.
import config as _config
_config.configure_logging(log_file=LOG_FILE)


def log(message: str) -> None:
    # Explicit UTF-8: open()'s default on Windows is the system codepage (cp1252),
    # which crashes on ordinary characters an LLM can produce in freeform text (a
    # narrow no-break space in a time like "8 AM", an emoji, etc).
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {message}\n")


def configure_task_settings(task_name: str) -> None:
    """Sets WakeToRun (so a sleeping machine wakes for the trigger) and Hidden
    (so the task's action never shows a window, even briefly) on an already-
    created scheduled task. Previously each of alarm.py/reminders.py/
    email_monitor.py/calendar_monitor.py duplicated an almost-identical
    WakeToRun-only version of this; consolidated here when Hidden was added to
    actually fix the console-flash bug (removing explorer.exe as the /tr
    wrapper and switching the .bat's interpreter to pythonw.exe closed the two
    biggest sources of it, but Hidden is the belt-and-suspenders setting for
    the cmd.exe window a .bat's own execution still briefly needs)."""
    try:
        subprocess.run([
            "powershell", "-Command",
            f'$task = Get-ScheduledTask -TaskName "{task_name}"; '
            f'$task.Settings.WakeToRun = $true; '
            f'$task.Settings.Hidden = $true; '
            f'Set-ScheduledTask -InputObject $task'
        ], capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        log(f"Could not configure task settings for {task_name!r}: {e}")


def wake_display() -> None:
    """Task Scheduler's wake-to-run wakes the system but not the monitor -- by
    design, since it's meant for silent background tasks. No single technique is
    guaranteed to force a display back on across every monitor/driver combination,
    so this layers three: declare the display is needed, explicitly tell the
    monitor to power on, and simulate a tiny mouse nudge (real input activity is
    the one thing Windows always respects as a reason to wake the display)."""
    try:
        import ctypes

        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_DISPLAY_REQUIRED = 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )

        HWND_BROADCAST = 0xFFFF
        WM_SYSCOMMAND = 0x0112
        SC_MONITORPOWER = 0xF170
        MONITOR_ON = -1
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_ON)

        MOUSEEVENTF_MOVE = 0x0001
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 1, 0, 0, 0)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, -1, 0, 0, 0)

        log("Attempted to wake the display")
    except Exception as e:
        log(f"Failed to wake display: {e}")


def _run_powercfg(value: str) -> bool:
    """Requires an elevated process token. Confirmed (2026-08-31 investigation):
    Alexis's own process is never elevated (it's launched normally, no UAC prompt),
    and Windows refuses to grant a scheduled task "Highest" run level from a
    non-elevated creator -- tried both `schtasks /rl highest` at creation and
    PowerShell `Set-ScheduledTask` after the fact, both denied with the same
    HRESULT 0x80070005. WakeToRun works because it doesn't grant elevated
    privileges to the task; changing the run level does, so it's gated harder.
    Fixing this for real needs either a one-time manual "Run with highest
    privileges" checkbox on the task (Task Scheduler GUI, done by the user, who
    IS an admin) or running all of Alexis elevated -- not worth the broadened
    attack surface for what's likely a minor effect (Windows generally keeps
    audio playing from an already-running background process through a locked
    session regardless of this setting)."""
    result = subprocess.run(
        ["powercfg", "/setacvalueindex", "SCHEME_CURRENT", "SUB_NONE", "CONSOLELOCK", value],
        capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW
    )
    if result.returncode != 0:
        return False
    subprocess.run(
        ["powercfg", "/setactive", "SCHEME_CURRENT"],
        capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW
    )
    return True


def disable_lock_requirement() -> None:
    try:
        if _run_powercfg("0"):
            log("Lock requirement temporarily disabled")
        else:
            log("Could not disable lock requirement (likely needs elevation) -- continuing anyway")
    except Exception as e:
        log(f"Failed to disable lock requirement: {e}")


def enable_lock_requirement() -> None:
    try:
        if _run_powercfg("1"):
            log("Lock requirement restored")
        else:
            log("Could not restore lock requirement (likely needs elevation) -- it was probably never actually disabled")
    except Exception as e:
        log(f"Failed to restore lock requirement: {e}")


def is_main_already_running() -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
             "| Where-Object { $_.CommandLine -like '*main.py*' }"],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW
        )
        return bool(result.stdout.strip())
    except Exception as e:
        log(f"is_main_already_running check failed: {e}")
        return False


def launch_main_if_not_running(extra_args: list[str] | None = None) -> None:
    if is_main_already_running():
        log("main.py already running, skipping launch")
        return

    args = [sys.executable, str(PROJECT_ROOT / "main.py")] + (extra_args or [])
    log(f"Launching main.py {' '.join(extra_args or [])}".strip())
    subprocess.Popen(args, cwd=str(PROJECT_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)


def butlerify(plain_message: str, style_hint: str) -> str:
    """Asks the LLM to re-deliver a plain message in a given style. Nice-to-have,
    not load-bearing: falls back to the plain message if the API is unreachable or
    rate-limited, since these scripts must never go silent over that."""
    from llm.groq_client import ask_groq

    prompt = (
        f"{style_hint} Keep every fact accurate, just change the delivery. "
        f"Facts: {plain_message} "
        "This will be spoken aloud: no markdown, no lists, no asterisks."
    )
    try:
        styled, _ = ask_groq(prompt)
    except Exception as e:
        log(f"Styled message generation failed: {e}")
        return plain_message

    if not styled or not styled.strip() or "trouble reaching my brain" in styled:
        log("Styled message unavailable, falling back to plain message.")
        return plain_message

    return styled.strip()
