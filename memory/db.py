"""SQLite-backed storage with a FAISS semantic index layered on top.

SQLite is the source of truth (structured, queryable, and — critically —
updatable in place: an `UPDATE ... WHERE id = ?` replaces a row atomically,
unlike rewriting a flat JSON file). FAISS is kept purely as a semantic search
index over the same rows, rebuilt into memory at startup and kept in sync
incrementally as rows are added or updated.
"""
import logging
import sqlite3
from pathlib import Path

import faiss
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def connect(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # Behavioral rules (tone, formatting, confirmation requirements, etc.) — always
    # loaded in full into the system prompt rather than semantically searched, since
    # they need to apply on every turn, not just when a query happens to match them.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def vector_to_blob(vector: np.ndarray) -> bytes:
    return vector.astype(np.float32).tobytes()


def blob_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class VectorIndex:
    """A FAISS index keyed by the same integer ids as the SQLite rows it mirrors,
    so a row can be updated in place: remove its old vector, add the new one under
    the same id. Rebuilt into memory from SQLite at startup; nothing is persisted
    to a separate cache file, so there's nothing that can drift out of sync with
    the database on disk."""

    def __init__(self, dim: int = EMBEDDING_DIM):
        self._index = faiss.IndexIDMap(faiss.IndexFlatL2(dim))

    def load(self, ids: list[int], vectors: list[np.ndarray]) -> None:
        if not ids:
            return
        self._index.add_with_ids(
            np.array(vectors, dtype=np.float32),
            np.array(ids, dtype=np.int64),
        )

    def upsert(self, row_id: int, vector: np.ndarray) -> None:
        id_arr = np.array([row_id], dtype=np.int64)
        if self._index.ntotal > 0:
            self._index.remove_ids(id_arr)
        self._index.add_with_ids(np.array([vector], dtype=np.float32), id_arr)

    def remove(self, row_id: int) -> None:
        if self._index.ntotal > 0:
            self._index.remove_ids(np.array([row_id], dtype=np.int64))

    def search(self, query_vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._index.ntotal == 0:
            return []
        k = min(k, self._index.ntotal)
        distances, ids = self._index.search(np.array([query_vector], dtype=np.float32), k)
        return [(int(i), float(d)) for i, d in zip(ids[0], distances[0]) if i != -1]
