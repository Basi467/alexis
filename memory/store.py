import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

from config import MEMORY_DB_FILE, MEMORY_FILE
from embedding_model import embedder
from llm.groq_client import ask_groq, CLASSIFICATION_MODEL
from memory.db import VectorIndex, blob_to_vector, connect, vector_to_blob

logger = logging.getLogger(__name__)

MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "Save a durable personal fact about the user for long-term memory — such as their name, age, career, goals, or strong preferences. Do not call this for temporary feelings, one-off requests, small talk, or ongoing project status (use update_project for that instead).",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "A short, third-person statement of the fact, e.g. 'User is 22 years old.'"
                }
            },
            "required": ["fact"]
        }
    }
}

RECALL_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": "Retrieve stored personal facts about the user — such as their name, age, career, goals, or preferences. Call this BEFORE claiming you don't know something about the user that isn't already in the current conversation, and BEFORE doing something that could be personalized to a known preference even if the user didn't explicitly ask about it — e.g. check for a music preference before playing music, not just when asked 'what music do I like'. Never say you don't know something about the user without checking this first.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for, e.g. 'user's name' or 'user's career goals'."
                }
            },
            "required": ["query"]
        }
    }
}

UPDATE_PROJECT_TOOL = {
    "type": "function",
    "function": {
        "name": "update_project",
        "description": "Create or update the tracked status of one of the user's ongoing projects. Use when the user mentions starting, making progress on, or finishing a specific named project or piece of work — not for one-off facts about the user themselves (use save_memory for that). Updating a project you already know about replaces its status rather than adding a duplicate.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The project's name, e.g. 'Alexis voice assistant' or 'API refactor'."},
                "status": {"type": "string", "description": "A short third-person summary of its current status, e.g. 'Rewriting the memory system to use SQLite.'"}
            },
            "required": ["name", "status"]
        }
    }
}

RECALL_PROJECT_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_project",
        "description": "Retrieve the current tracked status of one of the user's projects. Call this when the user asks about the status or progress of a specific project they've mentioned before.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The project's name or a description of it."}
            },
            "required": ["name"]
        }
    }
}

SAVE_RULE_TOOL = {
    "type": "function",
    "function": {
        "name": "save_behavior_rule",
        "description": "Save a durable instruction about how you (Alexis) should behave going forward — tone, formatting, confirmation requirements, things to always or never do. Not for facts about the user (use save_memory) or project status (use update_project). Use when the user corrects your behavior or tells you to change how you act, e.g. 'always ask before opening apps' or 'call me boss instead of sir'.",
        "parameters": {
            "type": "object",
            "properties": {
                "rule": {
                    "type": "string",
                    "description": "A short, imperative instruction, e.g. 'Always confirm before opening an application.'"
                }
            },
            "required": ["rule"]
        }
    }
}

# Distance below which two facts are considered candidates worth asking the LLM
# about (not necessarily duplicates — just plausibly about the same topic).
FACT_RELATED_DISTANCE = 1.0
MAX_CLASSIFICATION_CANDIDATES = 3


def _classify_update_or_new(new_text: str, candidates: list[tuple[int, str]]) -> int | None:
    """Asks the LLM whether new_text updates one of the candidate entries (same
    specific topic, corrected/newer info) or is a separate addition. Returns the
    id of the entry to update, or None if it should be saved as a new entry.

    This replaces pure embedding-distance dedup, which only catches near-verbatim
    restatements — a fact that meaningfully extends or contradicts an old one
    (e.g. 'user moved to a new city') is semantically distant enough from the old
    text that a fixed threshold alone can't tell it's the same topic."""
    if not candidates:
        return None

    numbered = "\n".join(f"{i + 1}. {text}" for i, (_id, text) in enumerate(candidates))
    prompt = (
        "You maintain a factual memory store about a user. Decide whether the NEW "
        "STATEMENT updates one of the EXISTING entries below (same specific topic, "
        "newer or corrected information) or is a separate, additional entry.\n\n"
        f"EXISTING:\n{numbered}\n\n"
        f"NEW STATEMENT: {new_text}\n\n"
        "Respond with ONLY the number of the entry it updates, or the word NEW. "
        "No other text."
    )

    reply, _ = ask_groq(prompt, model=CLASSIFICATION_MODEL)
    reply = reply.strip()

    match = re.search(r"\d+", reply)
    if match:
        idx = int(match.group()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx][0]
    return None

_conn = connect(MEMORY_DB_FILE)
_facts_index = VectorIndex()
_projects_index = VectorIndex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _embed(text: str):
    return embedder.encode([text], show_progress_bar=False)[0]


def _load_indexes() -> None:
    fact_rows = _conn.execute("SELECT id, embedding FROM facts").fetchall()
    _facts_index.load(
        [row["id"] for row in fact_rows],
        [blob_to_vector(row["embedding"]) for row in fact_rows],
    )

    project_rows = _conn.execute("SELECT id, embedding FROM projects").fetchall()
    _projects_index.load(
        [row["id"] for row in project_rows],
        [blob_to_vector(row["embedding"]) for row in project_rows],
    )


def _migrate_legacy_json() -> None:
    """One-time import of the old flat-file memories.json into the facts table,
    run only if that file exists and the new table is still empty."""
    if not os.path.exists(MEMORY_FILE):
        return
    existing_count = _conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    if existing_count > 0:
        return

    try:
        with open(MEMORY_FILE, "r") as f:
            legacy_memories = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Could not read legacy memory file for migration: %s", e)
        return

    if not legacy_memories:
        return

    logger.info("Migrating %d legacy memories into the new database.", len(legacy_memories))
    for entry in legacy_memories:
        text = entry.get("text")
        if not text:
            continue
        timestamp = entry.get("timestamp") or _now()
        vector = _embed(text)
        cursor = _conn.execute(
            "INSERT INTO facts (text, embedding, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (text, vector_to_blob(vector), timestamp, timestamp),
        )
        _facts_index.upsert(cursor.lastrowid, vector)
    _conn.commit()

    backup_path = str(MEMORY_FILE) + ".migrated"
    try:
        os.replace(MEMORY_FILE, backup_path)
        logger.info("Legacy memory file migrated and moved to %s", backup_path)
    except OSError:
        pass


_load_indexes()
_migrate_legacy_json()


def remember(text: str) -> None:
    """Save a fact. If it's a near-verbatim restatement of an existing fact, or the
    LLM judges it updates one (same topic, corrected/newer info — e.g. 'user moved
    to a new city'), that fact is overwritten in place instead of duplicated."""
    vector = _embed(text)
    matches = _facts_index.search(vector, k=MAX_CLASSIFICATION_CANDIDATES)
    candidate_ids = [fact_id for fact_id, dist in matches if dist < FACT_RELATED_DISTANCE]

    update_id = None
    if candidate_ids:
        candidates = []
        for fact_id in candidate_ids:
            row = _conn.execute("SELECT text FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row:
                candidates.append((fact_id, row["text"]))
        update_id = _classify_update_or_new(text, candidates)

    now = _now()
    if update_id is not None:
        _conn.execute(
            "UPDATE facts SET text = ?, embedding = ?, updated_at = ? WHERE id = ?",
            (text, vector_to_blob(vector), now, update_id),
        )
        _facts_index.upsert(update_id, vector)
        _conn.commit()
        logger.info("Updated existing fact (id=%d) instead of creating a duplicate.", update_id)
        return

    cursor = _conn.execute(
        "INSERT INTO facts (text, embedding, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (text, vector_to_blob(vector), now, now),
    )
    _facts_index.upsert(cursor.lastrowid, vector)
    _conn.commit()


def recall(query: str, max_results: int = 3, distance_threshold: float = 1.2) -> list[str]:
    vector = _embed(query)
    matches = _facts_index.search(vector, k=max_results)

    results = []
    for fact_id, dist in matches:
        if dist < distance_threshold:
            row = _conn.execute("SELECT text FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row:
                results.append(row["text"])
    return results


def _find_project_by_name(name: str, distance_threshold: float = 1.2) -> sqlite3.Row | None:
    """Three tiers, cheapest and most reliable first:
    1. Exact (case-insensitive) name match.
    2. Substring match, either direction — so 'alexis' finds 'Alexis voice
       assistant' and vice versa, without needing embeddings at all.
    3. Semantic search, for genuinely different wording of the same project.
    """
    exact = _conn.execute(
        "SELECT * FROM projects WHERE lower(name) = lower(?)", (name,)
    ).fetchone()
    if exact:
        return exact

    substring = _conn.execute(
        "SELECT * FROM projects WHERE lower(?) LIKE '%' || lower(name) || '%' "
        "OR lower(name) LIKE '%' || lower(?) || '%' "
        "ORDER BY length(name) DESC LIMIT 1",
        (name, name),
    ).fetchone()
    if substring:
        return substring

    vector = _embed(name)
    matches = _projects_index.search(vector, k=1)
    if matches and matches[0][1] < distance_threshold:
        project_id, _ = matches[0]
        return _conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()

    return None


def update_project(name: str, status: str) -> None:
    """Create a project, or update its status in place if a matching one already
    exists (see _find_project_by_name) — so 'Alexis', 'alexis voice assistant',
    and a semantically similar phrasing all land on the same project instead of
    fragmenting into near-duplicate entries."""
    existing = _find_project_by_name(name)

    vector = _embed(f"{name}: {status}")
    now = _now()

    if existing:
        project_id = existing["id"]
        _conn.execute(
            "UPDATE projects SET status = ?, embedding = ?, updated_at = ? WHERE id = ?",
            (status, vector_to_blob(vector), now, project_id),
        )
        _projects_index.upsert(project_id, vector)
    else:
        cursor = _conn.execute(
            "INSERT INTO projects (name, status, embedding, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, status, vector_to_blob(vector), now, now),
        )
        _projects_index.upsert(cursor.lastrowid, vector)

    _conn.commit()


def recall_project(name: str) -> dict | None:
    row = _find_project_by_name(name)
    if row:
        return {"name": row["name"], "status": row["status"], "updated_at": row["updated_at"]}
    return None


def save_rule(text: str) -> None:
    """Save a behavioral rule, or update an existing one in place if the LLM judges
    this contradicts/refines it (e.g. 'actually, casual tone is fine' should replace
    'always speak formally', not sit alongside it as a second, conflicting rule).
    No embeddings here — the rule set is expected to stay small, so every existing
    rule is just shown to the classifier directly rather than pre-filtered by
    similarity search."""
    existing_rules = _conn.execute("SELECT id, text FROM rules").fetchall()
    candidates = [(row["id"], row["text"]) for row in existing_rules]

    update_id = _classify_update_or_new(text, candidates) if candidates else None

    now = _now()
    if update_id is not None:
        _conn.execute(
            "UPDATE rules SET text = ?, updated_at = ? WHERE id = ?",
            (text, now, update_id),
        )
        logger.info("Updated existing behavior rule (id=%d).", update_id)
    else:
        _conn.execute(
            "INSERT INTO rules (text, created_at, updated_at) VALUES (?, ?, ?)",
            (text, now, now),
        )
    _conn.commit()


def get_all_rules() -> list[str]:
    rows = _conn.execute("SELECT text FROM rules ORDER BY id").fetchall()
    return [row["text"] for row in rows]
