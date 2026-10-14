import hashlib
import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_MODEL_CACHE_DIR = "data/models"
EMBEDDING_BATCH_SIZE = 64


@lru_cache(maxsize=1)
def load_embedding_model(cache_dir: str = DEFAULT_MODEL_CACHE_DIR) -> TextEmbedding:
    """Load the multilingual sentence encoder once, downloading it on first use."""
    return TextEmbedding(EMBEDDING_MODEL_NAME, cache_dir=cache_dir)


def embed_texts(texts: Sequence[str], cache_dir: str = DEFAULT_MODEL_CACHE_DIR) -> np.ndarray:
    """Encode texts into a matrix with one 384-dimensional row per text."""
    model = load_embedding_model(cache_dir)
    return np.array(list(model.embed(list(texts), batch_size=EMBEDDING_BATCH_SIZE)))


def fingerprint_texts(texts: Sequence[str]) -> str:
    """Return a stable hash of the texts and model name, used to validate cached embeddings."""
    digest = hashlib.sha256(EMBEDDING_MODEL_NAME.encode())
    for text in texts:
        digest.update(text.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def embed_texts_cached(texts: Sequence[str], cache_path: Path) -> np.ndarray:
    """Reuse embeddings saved for exactly these texts, computing and saving them otherwise."""
    fingerprint_path = cache_path.with_suffix(".json")
    fingerprint = fingerprint_texts(texts)
    if (
        fingerprint_path.exists()
        and cache_path.exists()
        and (json.loads(fingerprint_path.read_text())["fingerprint"] == fingerprint)
    ):
        return np.load(cache_path)
    embeddings = embed_texts(texts)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, embeddings)
    fingerprint_path.write_text(json.dumps({"fingerprint": fingerprint}))
    return embeddings
