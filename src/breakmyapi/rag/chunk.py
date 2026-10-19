"""Cut the downloaded documents into small sections ("chunks") that search can return.

Uses two LangChain text splitters, one after the other:
  1. MarkdownHeaderTextSplitter      cuts at # headings and keeps the headings as metadata
  2. RecursiveCharacterTextSplitter  cuts long sections down to MAX_CHARS, with a small overlap

Run from the project folder:  uv run python -m breakmyapi.rag.chunk
Reads corpus/raw/*.md and writes corpus/chunks.jsonl (one chunk per line).
"""

import json
from dataclasses import asdict, dataclass

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from breakmyapi.rag.fetch_corpus import CORPUS_DIR, RAW_DIR, load_sources

MAX_CHARS = 1500      # longest allowed chunk
OVERLAP_CHARS = 150   # each piece repeats the end of the previous one, so nothing is lost at a cut
MIN_CHARS = 80        # shorter pieces are dropped: too little meaning to be useful
CHUNKS_FILE = CORPUS_DIR / "chunks.jsonl"

# Which markdown headings to cut at, and the metadata key each one is stored under.
HEADING_LEVELS = [
    ("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4"), ("#####", "h5"), ("######", "h6"),
]

header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADING_LEVELS)
size_splitter = RecursiveCharacterTextSplitter(chunk_size=MAX_CHARS, chunk_overlap=OVERLAP_CHARS)


@dataclass
class Chunk:
    id: str
    source_id: str
    title: str
    url: str
    tags: list[str]
    heading: str
    text: str


def split_document(markdown: str) -> list[Document]:
    sections = header_splitter.split_text(markdown)   # step 1: one Document per heading section
    return size_splitter.split_documents(sections)    # step 2: long sections cut smaller (metadata is kept)


def heading_path(doc: Document) -> str:
    """{"h1": "API1:2023 ...", "h2": "How To Prevent"}  ->  "API1:2023 ... > How To Prevent" """
    return " > ".join(doc.metadata[key] for _, key in HEADING_LEVELS if key in doc.metadata)


def build_chunks() -> list[Chunk]:
    chunks = []
    for source in load_sources():
        markdown = (RAW_DIR / f"{source['id']}.md").read_text(encoding="utf-8")
        number = 0
        for piece in split_document(markdown):
            heading = heading_path(piece)
            if "References" in heading:
                continue  # lists of links: they say nothing useful to search
            if len(piece.page_content) < MIN_CHARS:
                continue
            number += 1
            chunks.append(Chunk(
                id=f"{source['id']}-{number:02d}",
                source_id=source["id"],
                title=source["title"],
                url=source["url"],
                tags=source["tags"],
                heading=heading,
                text=piece.page_content,
            ))
    return chunks


def main() -> None:
    chunks = build_chunks()
    with CHUNKS_FILE.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    sizes = [len(c.text) for c in chunks]
    print(f"{len(chunks)} chunks written to {CHUNKS_FILE}")
    print(f"length in characters: shortest {min(sizes)}, average {sum(sizes) // len(sizes)}, longest {max(sizes)}")


if __name__ == "__main__":
    main()
