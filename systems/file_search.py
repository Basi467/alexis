import logging
import os
from pathlib import Path

from config import BASE_DIR

logger = logging.getLogger(__name__)

SEARCH_FOLDERS = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
]

# Alexis's own project directory lives at Desktop/alexisv2 -- without this, walking
# the Desktop folder recurses straight into Alexis's own source code, logs, and
# scratch files. Confirmed live: this let find_file_by_name match and actually
# open scratch_debug.txt (a debug scratch file with real personal email content)
# when asked to find a resume, and let search_documents index the app's own
# alarm_log.txt as if it were a user document.
_PROJECT_ROOT = str(BASE_DIR.resolve())

EXCLUDED_FOLDER_NAMES = {
    "site-packages", "venv", "env", ".venv", "node_modules",
    "__pycache__", ".git", "dist-info", "egg-info",
    "Lib", "Scripts", "Include",  # common venv subfolder names
}

EXCLUDED_FILENAMES = {
    "license.txt", "authors.txt", "entry_points.txt", "top_level.txt",
    "requirements.txt", "readme.txt", "changelog.txt", "vendor.txt",
    "record.txt", "wheel", "metadata",
}


def _is_excluded_path(path_parts) -> bool:
    return any(part in EXCLUDED_FOLDER_NAMES for part in path_parts)


def _collect_files() -> list[dict]:
    files = []
    for folder in SEARCH_FOLDERS:
        if not folder.exists():
            continue
        for root, dirs, filenames in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_FOLDER_NAMES]

            resolved_root = str(Path(root).resolve())
            if resolved_root == _PROJECT_ROOT or resolved_root.startswith(_PROJECT_ROOT + os.sep):
                dirs[:] = []  # don't descend into it either
                continue

            for name in filenames:
                if name.lower() in EXCLUDED_FILENAMES:
                    continue
                # Microsoft Office's temp lock file for a currently-open document --
                # always this "~$" + original-name pattern, so an exact-name set
                # can't catch it. Confirmed live: these got picked up as "new"
                # files and fed to doc_store's re-indexer, which then failed trying
                # to parse them as real .docx packages (they're just lock markers).
                if name.startswith("~$"):
                    continue

                full_path = Path(root) / name
                try:
                    modified_time = full_path.stat().st_mtime
                    files.append({
                        "name": name,
                        "path": str(full_path),
                        "modified": modified_time
                    })
                except OSError:
                    continue
    return files


def find_file(query: str, file_extension: str | None = None, max_results: int = 3) -> list[dict]:
    files = _collect_files()
    query = query.lower()

    matches = []
    for f in files:
        if query in f["name"].lower():
            if file_extension and not f["name"].lower().endswith(file_extension.lower()):
                continue
            matches.append(f)
    matches.sort(key=lambda f: f["modified"], reverse=True)
    return matches[:max_results]


def search_and_describe(query: str, file_extension: str | None = None) -> str:
    results = find_file(query, file_extension=file_extension)
    if not results:
        return f"I couldn't find any files matching {query}."
    if len(results) == 1:
        return f"I found {results[0]['name']}."
    names = ", ".join(r["name"] for r in results[:3])
    return f"I found a few matches: {names}."


def open_file(filepath: str) -> str:
    try:
        os.startfile(filepath)
        return f"Opening {os.path.basename(filepath)}."
    except Exception as e:
        logger.error("Failed to open file %r: %s", filepath, e)
        return f"I couldn't open that file. Error: {e}"
