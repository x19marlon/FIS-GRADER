"""Shared, deterministic configuration for indexing and retrieval."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_LABEL = "src/classroom/rubrica.md"
SOURCE_DIRECTORY = PROJECT_ROOT / "src" / "classroom"
LANCEDB_URI = PROJECT_ROOT / ".rag_data"
TABLE_NAME = "rubric_chunks"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Generation settings are separate from the CPU embedding model.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_CONTEXT_SIZE = 4096
OLLAMA_KEEP_ALIVE = "5m"
OLLAMA_TIMEOUT = 180


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformerEmbedder:
    """Load the CPU embedder lazily and reuse it across bot questions."""

    from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(EMBED_MODEL, device="cpu")
