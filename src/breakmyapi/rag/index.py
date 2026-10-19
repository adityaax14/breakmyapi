"""Embed every chunk and store it in Postgres (the vector store).

Run from the project folder, with Postgres running:
  uv run python -m breakmyapi.rag.index
It rebuilds the table from scratch each time, so running it again is safe.
"""

import json
import time

from langchain_core.documents import Document

from breakmyapi.rag.chunk import CHUNKS_FILE
from breakmyapi.rag.store import create_table, get_store


def load_documents() -> tuple[list[Document], list[str]]:
    documents, ids = [], []
    with CHUNKS_FILE.open(encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            documents.append(Document(
                # The heading path goes in front of the text, so a short section such as
                # "Scenario #2" still says what it is about.
                page_content=f"{chunk['heading']}\n\n{chunk['text']}",
                metadata={
                    "source_id": chunk["source_id"],
                    "title": chunk["title"],
                    "url": chunk["url"],
                    "heading": chunk["heading"],
                    "tags": chunk["tags"],
                },
            ))
            ids.append(chunk["id"])
    return documents, ids


def main() -> None:
    documents, ids = load_documents()
    print(f"{len(documents)} chunks to embed")

    create_table()
    start = time.perf_counter()
    get_store().add_documents(documents, ids=ids)
    print(f"embedded and stored in {time.perf_counter() - start:.1f} seconds")


if __name__ == "__main__":
    main()
