"""Central configuration: paths, environment variables, and logging setup.

All modules should import paths and API keys from here instead of hardcoding
absolute paths or calling load_dotenv()/os.environ.get() themselves.
"""
import logging
import os
from pathlib import Path

# Must be set before sentence_transformers/huggingface_hub are imported anywhere
# (config.py is always imported first) -- this is the officially supported way to
# turn off their "Loading weights" / download progress bars, which don't go
# through the logging module at all so setLevel() below can't touch them.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

# --- API keys ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI")

# --- Paths ---
MEMORY_DIR = BASE_DIR / "memory"
MEMORY_FILE = MEMORY_DIR / "memories.json"  # legacy flat-file store, migrated from on first run
MEMORY_INDEX_CACHE_FILE = MEMORY_DIR / "memory_index_cache.pkl"
MEMORY_DB_FILE = MEMORY_DIR / "memory.db"

SYSTEMS_DIR = BASE_DIR / "systems"
DOCUMENT_INDEX_CACHE_FILE = SYSTEMS_DIR / "document_index_cache.pkl"

SCHEDULER_DIR = BASE_DIR / "scheduler"
TASKS_FILE = SCHEDULER_DIR / "tasks.json"
ALARM_LOG_FILE = SCHEDULER_DIR / "alarm_log.txt"

MODELS_DIR = BASE_DIR / "models"
VOSK_MODEL_PATH = MODELS_DIR / "vosk-model-small-en-us-0.15"

SPOTIFY_CACHE_PATH = BASE_DIR / ".spotify_cache"

GMAIL_CREDENTIALS_FILE = BASE_DIR / "gmail_credentials.json"  # downloaded from Google Cloud Console, one-time setup
GMAIL_TOKEN_FILE = BASE_DIR / ".gmail_token.json"              # cached after first OAuth login
EMAIL_CHECK_STATE_FILE = SCHEDULER_DIR / "email_check_state.json"  # tracks last-seen email for background polling
CALENDAR_CHECK_STATE_FILE = SCHEDULER_DIR / "calendar_check_state.json"  # tracks already-announced events

PYTHON_EXECUTABLE = Path(os.sys.executable)
# Scheduled-task entry scripts (alarm/reminders/email+calendar monitors) should
# run with no console at all -- pythonw.exe is the windowless build that ships
# alongside python.exe for exactly this. Using python.exe there is what caused
# a real, confirmed bug: a visible console window flashing open and closed on
# every background check.
PYTHONW_EXECUTABLE = PYTHON_EXECUTABLE.parent / "pythonw.exe"
MAIN_SCRIPT_PATH = BASE_DIR / "main.py"


# Third-party libraries that use the standard `logging` module inherit whatever
# level configure_logging() sets on the root logger -- at INFO, that includes
# every single HTTP request httpx makes and every retry groq's SDK logs
# internally, neither of which is useful noise for this app's own logs.
_NOISY_THIRD_PARTY_LOGGERS = ("httpx", "httpcore", "groq", "faiss", "sentence_transformers")
# huggingface_hub's "unauthenticated requests" reminder is emitted at WARNING, so
# it needs bumping all the way to ERROR to actually go away -- WARNING wouldn't do it.
_ERROR_ONLY_LOGGERS = ("huggingface_hub",)


def configure_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """Set up root logging once. Safe to call multiple times."""
    handlers = [logging.StreamHandler()]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    for name in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in _ERROR_ONLY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)

    # huggingface_hub's "unauthenticated requests" nag doesn't respect a plain
    # logging.getLogger("huggingface_hub").setLevel() call -- it's emitted through
    # the library's own internal logging wrapper, which needs its own API.
    try:
        from huggingface_hub.utils import logging as hf_logging
        hf_logging.set_verbosity_error()
    except ImportError:
        pass
