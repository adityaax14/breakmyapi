"""Tests for rag/answer.py: building the RAG prompt and reading the citations."""

from breakmyapi.rag.answer import body_of, build_prompt, cited_numbers
from breakmyapi.rag.search import Hit

HITS = [
    Hit("doc-a-01", "Doc A > How To Prevent", "https://example.org/a", 0.71, "Doc A > How To Prevent\n\nUse an allowlist."),
    Hit("doc-b-02", "Doc B", "https://example.org/b", 0.64, "Doc B\n\nCheck who owns the record."),
]


def test_body_drops_the_heading_line():
    assert body_of(HITS[0]) == "Use an allowlist."


def test_prompt_numbers_the_sources_and_ends_with_the_question():
    prompt = build_prompt("How do I fix it?", HITS)
    assert "[1] Doc A > How To Prevent\nUse an allowlist." in prompt
    assert "[2] Doc B\nCheck who owns the record." in prompt
    assert prompt.endswith("QUESTION: How do I fix it?")


def test_citations_are_found_once_each_and_sorted():
    assert cited_numbers("first [2], then [1], again [2]", how_many=2) == [1, 2]


def test_citations_of_sources_that_do_not_exist_are_ignored():
    assert cited_numbers("see [3] and [0]", how_many=2) == []
