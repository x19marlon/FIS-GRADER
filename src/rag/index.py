"""CocoIndex pipeline for the project rubric.

Build or incrementally update the index with:

    cocoindex update src.rag.index
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Annotated, AsyncIterator

import cocoindex as coco
from cocoindex.connectors import lancedb, localfs
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.ops.text import RecursiveSplitter
from cocoindex.resources.chunk import Chunk
from cocoindex.resources.file import FileLike, PatternFilePathMatcher
from cocoindex.resources.id import IdGenerator
from numpy.typing import NDArray

from .config import (
    LANCEDB_URI,
    SOURCE_DIRECTORY,
    SOURCE_LABEL,
    TABLE_NAME,
    get_embedder,
)

LANCE_DB = coco.ContextKey[lancedb.LanceAsyncConnection]("fis_grader_rag_db")
EMBEDDER = coco.ContextKey[SentenceTransformerEmbedder]("fis_grader_rag_embedder", detect_change=True)

_splitter = RecursiveSplitter()


@dataclass
class RubricChunk:
    """One traceable rubric passage stored in the vector index."""

    id: int
    source: str
    chunk_start: int
    chunk_end: int
    text: str
    embedding: Annotated[NDArray, EMBEDDER]


@coco.lifespan
async def coco_lifespan(builder: coco.EnvironmentBuilder) -> AsyncIterator[None]:
    """Provide the local database and local embedding model to CocoIndex."""

    LANCEDB_URI.mkdir(parents=True, exist_ok=True)
    builder.settings.db_path = LANCEDB_URI / "cocoindex.db"
    connection = await lancedb.connect_async(str(LANCEDB_URI))
    builder.provide(LANCE_DB, connection)
    builder.provide(EMBEDDER, get_embedder())
    yield


@coco.fn
async def process_chunk(
    chunk: Chunk,
    file_path: PurePath,
    id_generator: IdGenerator,
    table: lancedb.TableTarget[RubricChunk],
) -> None:
    """Embed and declare one chunk as managed LanceDB target state."""

    table.declare_row(
        row=RubricChunk(
            id=await id_generator.next_id(f"{file_path}:{chunk.text}"),
            source=SOURCE_LABEL,
            chunk_start=chunk.start.char_offset,
            chunk_end=chunk.end.char_offset,
            text=chunk.text,
            embedding=await coco.use_context(EMBEDDER).embed(chunk.text),
        )
    )


@coco.fn(memo=True)
async def process_file(
    file: FileLike,
    table: lancedb.TableTarget[RubricChunk],
) -> None:
    """Split a changed rubric file into overlapping, position-tracked chunks."""

    text = await file.read_text()
    chunks = _splitter.split(
        text,
        # Keep Spanish passages below MiniLM's 256-token input window.
        chunk_size=600,
        chunk_overlap=100,
        language="markdown",
    )
    id_generator = IdGenerator()
    await coco.map(process_chunk, chunks, file.file_path.path, id_generator, table)


@coco.fn
async def app_main(source_directory: Path) -> None:
    """Mount the source file and its managed local LanceDB target."""

    table = await lancedb.mount_table_target(
        LANCE_DB,
        table_name=TABLE_NAME,
        table_schema=await lancedb.TableSchema.from_class(
            RubricChunk,
            primary_key=["id"],
        ),
    )
    # Exact vector search needs no trained ANN index for this small corpus.
    files = localfs.walk_dir(
        source_directory,
        recursive=False,
        path_matcher=PatternFilePathMatcher(included_patterns=["rubrica.md"]),
        live=True,
    )
    await coco.mount_each(process_file, files.items(), table)


app = coco.App(
    coco.AppConfig(name="FISGraderRubricRAG"),
    app_main,
    source_directory=SOURCE_DIRECTORY,
)
