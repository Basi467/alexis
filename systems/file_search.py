import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SEARCH_FOLDERS = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
]

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

            for name in filenames:
                if name.lower() in EXCLUDED_FILENAMES:
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
