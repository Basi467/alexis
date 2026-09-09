import sys
from pathlib import Path

# See deliver_alarm.py for why this bootstrap is needed before importing scheduler.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))

from scheduler.system_helpers import log, launch_main_if_not_running


def main() -> None:
    # launch_main_if_not_running() logs its own outcome either way (skipped
    # because it's already running, or actually relaunched it) -- that's the
    # whole point here, so a relaunch after a real crash leaves a clear trail
    # in alarm_log.txt instead of the recovery happening invisibly.
    launch_main_if_not_running()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # See deliver_alarm.py -- pythonw.exe has no console, so an uncaught
        # exception's default traceback (sys.stderr, which is None here) would
        # otherwise vanish with zero trace anywhere.
        log(f"UNCAUGHT ERROR in watchdog check: {e!r}")
        raise
