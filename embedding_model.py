"""The one shared SentenceTransformer instance for the whole app. memory/store.py
and systems/doc_store.py both need embeddings, but each used to construct its own
separate model instance -- meaning it loaded from disk twice on every startup,
doubling that part of the startup delay for no benefit, since it's the exact same
model both times."""
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer("all-MiniLM-L6-v2")
