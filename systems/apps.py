import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

START_MENU_FOLDERS = [
    Path(os.environ["ProgramData"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]


def _find_shortcut(app_name: str) -> str | None:
    app_name = app_name.lower().strip()

    for folder in START_MENU_FOLDERS:
        if not folder.exists():
            continue
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(".lnk") and app_name in file.lower():
                    return str(Path(root) / file)

    return None


def _find_app_via_startapps(app_name: str) -> str | None:
    app_name_lower = app_name.lower().strip()

    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-StartApps | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        apps = json.loads(result.stdout)

        if isinstance(apps, dict):
            apps = [apps]

        for app in apps:
            if app_name_lower in app["Name"].lower():
                return app["AppID"]

    except Exception as e:
        logger.warning("Get-StartApps lookup failed: %s", e)

    return None


def open_app(app_name: str) -> str:
    shortcut = _find_shortcut(app_name)
    if shortcut:
        try:
            os.startfile(shortcut)
            return f"Opening {app_name}."
        except Exception as e:
            logger.error("Failed to open shortcut for %r: %s", app_name, e)
            return f"I found {app_name}, but couldn't open it. Error: {e}"

    app_id = _find_app_via_startapps(app_name)
    if app_id:
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
            return f"Opening {app_name}."
        except Exception as e:
            logger.error("Failed to launch app id %r: %s", app_id, e)
            return f"I found {app_name}, but couldn't open it. Error: {e}"

    return f"I couldn't find an app called {app_name} on this computer."
