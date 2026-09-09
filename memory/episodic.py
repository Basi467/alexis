"""Searchable log of past conversation exchanges -- lets Alexis answer "what
did we talk about yesterday" or "did I mention wanting to learn Rust before",
which the existing facts/projects/rules tables can't do since those only store
durable, deduped facts, not a timestamped history of actual exchanges.

Timestamps are stored as naive local time (datetime.now(), no UTC conversion)
to match how llm/router.py's _build_system_prompt() injects "current date and
time" for the model to compute relative dates from (also naive local, e.g. for
set_reminder) -- storing these in UTC instead would create a real mismatch at
day boundaries for a user meaningfully offset from UTC.
"""
import logging
from datetime import datetime

from config import MEMORY_DB_FILE
from embedding_model import embedder
from memory.db import VectorIndex, blob_to_vector, connect, vector_to_blob

logger = logging.getLogger(__name__)

MAX_EXCHANGE_PREVIEW_CHARS = 300  # keeps a search result's prompt contribution bounded

_conn = connect(MEMORY_DB_FILE)

_conn.execute("""
    CREATE TABLE IF NOT EXISTS conversation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_text TEXT NOT NULL,
        assistant_text TEXT NOT NULL,
        embedding BLOB NOT NULL,
        timestamp TEXT NOT NULL
    )
""")
_conn.commit()

_log_index = VectorIndex()


def _now() -> str:
    return datetime.now().isoformat()


def _embed(text: str):
    return embedder.encode([text], show_progress_bar=False)[0]


def _load_index() -> None:
    rows = _conn.execute("SELECT id, embedding FROM conversation_log").fetchall()
    _log_index.load(
        [row["id"] for row in rows],
        [blob_to_vector(row["embedding"]) for row in rows],
    )


_load_index()


def log_exchange(user_text: str, assistant_text: str) -> None:
    """Persists one user/assistant exchange for later episodic recall. Called
    after every real turn in main.py's conversation loop -- best-effort, a
    failure here should never break the actual conversation (callers should
    wrap this in a try/except, same as every other non-critical side effect
    in this app)."""
    if not user_text or not user_text.strip():
        return

    vector = _embed(user_text)
    cursor = _conn.execute(
        "INSERT INTO conversation_log (user_text, assistant_text, embedding, timestamp) VALUES (?, ?, ?, ?)",
        (user_text, assistant_text, vector_to_blob(vector), _now()),
    )
    _log_index.upsert(cursor.lastrowid, vector)
    _conn.commit()


DISTANCE_THRESHOLD = 1.2  # matches memory/store.py's recall() threshold -- beyond this,
# a semantic "match" is unrelated enough that returning it would just be noise.


def search_conversation_history(
    query: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Returns matching past exchanges, most recent first. `query` does
    semantic search over what the user said (omit for a pure date-range
    listing); `start_date`/`end_date` are "YYYY-MM-DD" strings that filter by
    when the exchange happened, inclusive on both ends -- either or both can
    be used together, matching how the user might actually ask: "what did we
    talk about yesterday" (date only), "did I mention Rust" (query only), "did
    we talk about the interview last week" (both)."""
    if query:
        vector = _embed(query)
        # Over-fetch before date-filtering, since a date range can eliminate
        # most semantic matches and we still want up to max_results after that.
        matches = _log_index.search(vector, k=max_results * 4)
        candidate_ids = [m[0] for m in matches if m[1] < DISTANCE_THRESHOLD]
        if not candidate_ids:
            return []
        placeholders = ",".join("?" * len(candidate_ids))
        rows = _conn.execute(
            f"SELECT * FROM conversation_log WHERE id IN ({placeholders})",
            candidate_ids,
        ).fetchall()
        rows_by_id = {r["id"]: r for r in rows}
        ordered_rows = [rows_by_id[i] for i in candidate_ids if i in rows_by_id]
    else:
        ordered_rows = _conn.execute(
            "SELECT * FROM conversation_log ORDER BY timestamp DESC LIMIT ?",
            (max_results * 4,),
        ).fetchall()

    results = []
    for row in ordered_rows:
        ts_date = row["timestamp"][:10]  # "YYYY-MM-DD" prefix -- date-only comparison
        # avoids time-of-day edge cases (e.g. an inclusive end_date otherwise
        # excluding same-day exchanges that happened later that day).
        if start_date and ts_date < start_date:
            continue
        if end_date and ts_date > end_date:
            continue
        results.append({
            "user_text": row["user_text"],
            "assistant_text": row["assistant_text"],
            "timestamp": row["timestamp"],
        })
        if len(results) >= max_results:
            break

    return results


def describe_conversation_history(results: list[dict]) -> str:
    if not results:
        return ""
    parts = []
    for r in results:
        when = r["timestamp"][:16].replace("T", " ")  # "YYYY-MM-DD HH:MM"
        user_preview = r["user_text"][:MAX_EXCHANGE_PREVIEW_CHARS]
        reply_preview = r["assistant_text"][:MAX_EXCHANGE_PREVIEW_CHARS]
        parts.append(f'At {when}, you said "{user_preview}" and I replied "{reply_preview}"')
    return ". ".join(parts) + "."


SEARCH_CONVERSATION_HISTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_conversation_history",
        "description": "Search past conversation exchanges (not durable facts -- use recall_memory for those) to answer things like 'what did we talk about yesterday', 'did I mention X before', or 'what did you tell me about Y last week'. Use the current date/time already given to you to compute start_date/end_date for relative phrasing like 'yesterday' or 'last week'.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": ["string", "null"], "description": "What topic/content to search for. Omit or use null for a pure date-range listing with no topic filter."},
                "start_date": {"type": ["string", "null"], "description": "Earliest date to include, as YYYY-MM-DD. Omit or use null for no lower bound."},
                "end_date": {"type": ["string", "null"], "description": "Latest date to include, as YYYY-MM-DD. Omit or use null for no upper bound."},
            },
        }
    }
}
