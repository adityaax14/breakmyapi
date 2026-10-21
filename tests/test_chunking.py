"""Tests for rag/chunk.py: cutting markdown into labelled chunks."""

from breakmyapi.rag.chunk import MAX_CHARS, heading_path, split_document

MARKDOWN = """# Guide

Some introduction text.

## How To Prevent

* Check that the record belongs to the caller.

```python
# this line is a code comment, not a heading
x = 1
```
"""


def test_each_section_gets_its_heading_path():
    headings = [heading_path(piece) for piece in split_document(MARKDOWN)]
    assert headings == ["Guide", "Guide > How To Prevent"]


def test_a_hash_inside_a_code_example_is_not_a_heading():
    headings = [heading_path(piece) for piece in split_document(MARKDOWN)]
    assert not any("code comment" in h for h in headings)


def test_long_sections_are_cut_to_the_size_limit():
    long_section = "# Big\n\n" + "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(40))
    pieces = split_document(long_section)
    assert len(pieces) > 1
    assert all(len(p.page_content) <= MAX_CHARS for p in pieces)
    assert all(heading_path(p) == "Big" for p in pieces)  # every piece keeps its heading
