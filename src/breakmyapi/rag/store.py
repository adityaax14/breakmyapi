"""The one door to the RAG library: the embedding model, and the vector store in Postgres."""

import asyncio
from functools import lru_cache
from threading import Thread

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import Column, PGEngine, PGVectorStore
from sqlalchemy.ext.asyncio import create_async_engine

from breakmyapi.config import get_settings

TABLE = "owasp_chunks"
VECTOR_SIZE = 384  # bge-small-en-v1.5 turns any text into a list of 384 numbers

# Labels stored as real table columns (not hidden inside JSON), so searches can filter on them.
TEXT_COLUMNS = ["source_id", "title", "url", "heading"]
METADATA_COLUMNS = [Column(name, "TEXT") for name in TEXT_COLUMNS] + [Column("tags", "TEXT[]")]


@lru_cache
def get_embeddings() -> HuggingFaceEmbeddings:
    # Runs on this computer. The model (about 130 MB) is downloaded once, on first use.
    return HuggingFaceEmbeddings(
        model_name=get_settings().embedding_model,
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache
def get_engine() -> PGEngine:
    # PGEngine talks to Postgres asynchronously, on an event loop running in a background thread.
    # psycopg's async mode cannot use Windows' default loop, so we give it a "selector" loop,
    # which works on every operating system.
    loop = asyncio.SelectorEventLoop()
    Thread(target=loop.run_forever, daemon=True).start()
    return PGEngine.from_engine(create_async_engine(get_settings().database_url), loop=loop)


def create_table() -> None:
    """Create the empty table, deleting any previous one."""
    get_engine().init_vectorstore_table(
        table_name=TABLE,
        vector_size=VECTOR_SIZE,
        metadata_columns=METADATA_COLUMNS,
        id_column=Column("chunk_id", "TEXT", nullable=False),
        overwrite_existing=True,
    )


@lru_cache
def get_store() -> PGVectorStore:
    return PGVectorStore.create_sync(
        engine=get_engine(),
        embedding_service=get_embeddings(),
        table_name=TABLE,
        id_column="chunk_id",
        metadata_columns=TEXT_COLUMNS + ["tags"],
    )
