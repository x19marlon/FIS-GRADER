"""Semantic retrieval over the locally indexed project rubric."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

from cocoindex.connectors import lancedb

from .config import LANCEDB_URI, TABLE_NAME, get_embedder


@dataclass(frozen=True)
class RetrievedChunk:
    """A rubric passage returned by a vector similarity search."""

    id: int
    source: str
    text: str
    chunk_start: int
    chunk_end: int
    score: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation for callers."""

        return asdict(self)


async def retrieve(question: str, top_k: int = 5) -> list[RetrievedChunk]:
    """Return the most relevant rubric chunks for ``question``.

    The query uses the same local Sentence Transformers model as the
    CocoIndex ingestion pipeline. ``score`` is derived from LanceDB's cosine
    distance only when LanceDB returns that distance.
    """

    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("The question cannot be empty.")
    if len(normalized_question) > 2000:
        raise ValueError("La pregunta debe tener como máximo 2000 caracteres.")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")
    if not LANCEDB_URI.exists():
        raise RuntimeError(
            "The RAG index does not exist. Run `cocoindex update src.rag.index` first."
        )

    try:
        connection = await lancedb.connect_async(str(LANCEDB_URI))
        table = await connection.open_table(TABLE_NAME)
        if await table.count_rows() == 0:
            return []
        # The CocoIndex embedder loads/executes the model in its async runner.
        embedder = get_embedder()
        query_embedding = await embedder.embed(normalized_question)
        search = await table.search(query_embedding, vector_column_name="embedding")
        rows = await search.distance_type("cosine").limit(top_k).to_list()
    except Exception as error:
        raise RuntimeError(
            "No se pudo consultar el índice local. "
            "Ejecuta `cocoindex update src.rag.index` y revisa la instalación del RAG."
        ) from error

    chunks = []
    for row in rows:
        distance = row.get("_distance")
        score = 1.0 - float(distance) if distance is not None else None
        chunks.append(
            RetrievedChunk(
                id=int(row["id"]),
                source=str(row["source"]),
                text=str(row["text"]),
                chunk_start=int(row["chunk_start"]),
                chunk_end=int(row["chunk_end"]),
                score=score,
            )
        )
    return chunks


def main() -> None:
    """Inspect retrieval without Telegram or an LLM API key."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    try:
        chunks = asyncio.run(retrieve(args.question, args.top_k))
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps([chunk.to_dict() for chunk in chunks], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
