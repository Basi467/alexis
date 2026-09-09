import logging
import subprocess

import screen_brightness_control as sbc
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

logger = logging.getLogger(__name__)

# This machine has no laptop-integrated panel, so screen_brightness_control logs a
# "failed to gather list of laptop displays" warning on every single call while it
# probes for one — harmless, but would spam the log every time brightness changes.
logging.getLogger("screen_brightness_control").setLevel(logging.ERROR)


def _volume_interface() -> IAudioEndpointVolume:
    return AudioUtilities.GetSpeakers().EndpointVolume


def set_volume(percent: int) -> str:
    percent = max(0, min(100, percent))
    try:
        _volume_interface().SetMasterVolumeLevelScalar(percent / 100.0, None)
        return f"Volume set to {percent} percent."
    except Exception as e:
        logger.error("Failed to set volume: %s", e)
        return f"I couldn't change the volume. Error: {e}"


def mute_volume() -> str:
    try:
        _volume_interface().SetMute(1, None)
        return "Muted."
    except Exception as e:
        logger.error("Failed to mute: %s", e)
        return f"I couldn't mute the volume. Error: {e}"


def unmute_volume() -> str:
    try:
        _volume_interface().SetMute(0, None)
        return "Unmuted."
    except Exception as e:
        logger.error("Failed to unmute: %s", e)
        return f"I couldn't unmute the volume. Error: {e}"


def set_brightness(percent: int) -> str:
    # Handles both laptop panels (WMI) and external monitors (DDC/CI) automatically,
    # unlike a raw WMI call which only works for laptop-integrated displays.
    percent = max(0, min(100, percent))
    try:
        sbc.set_brightness(percent)
        return f"Brightness set to {percent} percent."
    except Exception as e:
        logger.error("Failed to set brightness: %s", e)
        return f"I couldn't change the brightness. Error: {e}"


def close_app(app_name: str) -> str:
    process_name = app_name if app_name.lower().endswith(".exe") else f"{app_name}.exe"
    try:
        result = subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return f"I couldn't find {app_name} running."
        return f"Closed {app_name}."
    except Exception as e:
        logger.error("Failed to close app %r: %s", app_name, e)
        return f"I couldn't close {app_name}. Error: {e}"


def switch_to_app(app_name: str) -> str:
    try:
        import win32con
        import win32gui

        matches: list[int] = []

        def _enum_handler(hwnd: int, _: None) -> None:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and app_name.lower() in title.lower():
                    matches.append(hwnd)

        win32gui.EnumWindows(_enum_handler, None)

        if not matches:
            return f"I couldn't find a window for {app_name}."

        hwnd = matches[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return f"Switched to {app_name}."
    except Exception as e:
        logger.error("Failed to switch to app %r: %s", app_name, e)
        return f"I couldn't switch to {app_name}. Error: {e}"


def lock_computer() -> str:
    try:
        subprocess.run(
            ["rundll32.exe", "user32.dll,LockWorkStation"], timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Locking the computer."
    except Exception as e:
        logger.error("Failed to lock computer: %s", e)
        return f"I couldn't lock the computer. Error: {e}"


def restart_computer() -> str:
    try:
        subprocess.run(
            ["shutdown", "/r", "/t", "10"], timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Restarting the computer in 10 seconds. Say 'cancel shutdown' quickly if that's a mistake."
    except Exception as e:
        logger.error("Failed to restart computer: %s", e)
        return f"I couldn't restart the computer. Error: {e}"


def shutdown_computer() -> str:
    try:
        subprocess.run(
            ["shutdown", "/s", "/t", "10"], timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Shutting down the computer in 10 seconds. Say 'cancel shutdown' quickly if that's a mistake."
    except Exception as e:
        logger.error("Failed to shut down computer: %s", e)
        return f"I couldn't shut down the computer. Error: {e}"


def cancel_shutdown() -> str:
    try:
        subprocess.run(
            ["shutdown", "/a"], timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Cancelled the pending shutdown or restart."
    except Exception as e:
        logger.error("Failed to cancel shutdown: %s", e)
        return f"There was nothing to cancel, or it was too late. Error: {e}"
