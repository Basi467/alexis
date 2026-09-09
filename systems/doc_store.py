import logging
import os
import pickle
from pathlib import Path

import faiss
import numpy as np

from config import DOCUMENT_INDEX_CACHE_FILE
from embedding_model import embedder
from systems.doc_reader import chunk_text, extract_text
from systems.file_search import _collect_files

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt"]

_indexed_records: list[dict] = []   # each: {source_path, modified, chunk_index, text, vector}
_index: faiss.IndexFlatL2 | None = None
_last_found_file: str | None = None


def _reindex_file(filepath: str, modified_time: float) -> list[dict]:
    text = extract_text(filepath)
    if text.startswith("[Error") or text.startswith("[Unsupported"):
        return []

    chunks = chunk_text(text)
    if not chunks:
        return []

    vectors = embedder.encode(chunks, show_progress_bar=False).astype("float32")

    records = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        records.append({
            "source_path": filepath,
            "source_file": Path(filepath).name,
            "modified": modified_time,
            "chunk_index": i,
            "text": chunk,
            "vector": vector
        })
    return records


def _save_index_to_disk() -> None:
    with open(DOCUMENT_INDEX_CACHE_FILE, "wb") as f:
        pickle.dump(_indexed_records, f)


def _load_index_from_disk() -> None:
    global _indexed_records
    if os.path.exists(DOCUMENT_INDEX_CACHE_FILE):
        with open(DOCUMENT_INDEX_CACHE_FILE, "rb") as f:
            _indexed_records = pickle.load(f)


def update_document_index() -> None:
    global _indexed_records, _index

    if not _indexed_records:
        _load_index_from_disk()
        logger.debug("Loaded %d records from disk", len(_indexed_records))
    else:
        logger.debug("Already had %d records in memory", len(_indexed_records))

    current_files = _collect_files()
    current_files = [f for f in current_files if Path(f["name"]).suffix.lower() in SUPPORTED_EXTENSIONS]

    already_indexed = {r["source_path"]: r["modified"] for r in _indexed_records}

    new_records = []
    changed = False

    for f in current_files:
        path = f["path"]
        modified = f["modified"]

        if path in already_indexed and already_indexed[path] == modified:
            kept = [r for r in _indexed_records if r["source_path"] == path]
            new_records.extend(kept)
        else:
            logger.info("Indexing changed/new file: %s", f["name"])
            new_records.extend(_reindex_file(path, modified))
            changed = True

    if len(new_records) != len(_indexed_records):
        changed = True

    _indexed_records = new_records

    if changed:
        _save_index_to_disk()

    if not _indexed_records:
        _index = None
        return

    vectors = np.array([r["vector"] for r in _indexed_records]).astype("float32")
    _index = faiss.IndexFlatL2(vectors.shape[1])
    _index.add(vectors)


def search_documents(query: str, max_results: int = 6, distance_threshold: float = 1.5) -> list[dict]:
    update_document_index()  # cheap if nothing changed, does real work only for new/changed files

    if _index is None:
        return []

    query_vector = embedder.encode([query], show_progress_bar=False).astype("float32")
    k = min(max_results, len(_indexed_records))
    distances, indices = _index.search(query_vector, k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if dist < distance_threshold:
            results.append(_indexed_records[idx])

    return results


def set_last_found_file(path: str) -> None:
    global _last_found_file
    _last_found_file = path


def get_last_found_file() -> str | None:
    return _last_found_file
