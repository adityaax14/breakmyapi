"""Search the OWASP library by meaning. The agent's `retrieve` step will call search()."""

from dataclasses import dataclass
from functools import lru_cache

from breakmyapi.checks import CHECKS
from breakmyapi.rag.fetch_corpus import load_sources
from breakmyapi.rag.store import get_store

# The bge models were trained with this sentence in front of search questions
# (but not in front of the stored chunks). Adding it can help short questions.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@dataclass
class Hit:
    chunk_id: str
    heading: str
    url: str
    similarity: float
    text: str


@lru_cache
def documents_for_check(check: str) -> list[str]:
    """Which documents are tagged with a check, e.g. "mass_assignment" -> ["api3-bopla", "cs-mass-assignment"]."""
    if check not in CHECKS:
        raise ValueError(f"unknown check: {check}")
    return [source["id"] for source in load_sources() if check in source["tags"]]


def search(question: str, k: int = 3, check: str | None = None, instruction: bool = False) -> list[Hit]:
    """Return the k chunks closest in meaning to the question.

    check:       only search documents tagged with this check (for example "mass_assignment")
    instruction: put QUERY_INSTRUCTION in front of the question. Off by default, because
                 eval_retrieval.py showed it did not help (and hurt without the check filter).
    """
    query = QUERY_INSTRUCTION + question if instruction else question

    # The store cannot filter on "the tags list contains X", but every chunk of a document
    # has the same tags, so we filter on "comes from one of the documents tagged X" instead.
    search_filter = {"source_id": {"$in": documents_for_check(check)}} if check else None

    results = get_store().similarity_search_with_score(query, k=k, filter=search_filter)
    return [
        Hit(
            chunk_id=doc.id,
            heading=doc.metadata["heading"],
            url=doc.metadata["url"],
            similarity=round(1 - distance, 3),
            text=doc.page_content,
        )
        for doc, distance in results
    ]
