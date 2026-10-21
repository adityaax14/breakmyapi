"""Ask the OWASP library a question: find the best chunks, then let the LLM answer FROM them.

This is the "augmented generation" half of RAG: search.py finds the sources,
this file puts them into the prompt and asks the model to answer with citations.
"""

import re
from dataclasses import dataclass

from breakmyapi.llm.client import ask
from breakmyapi.rag.search import Hit, search

NOT_COVERED = "The library does not cover this."

SYSTEM = (
    "You answer questions about API security using ONLY the numbered sources you are given. "
    "After each claim, cite the source number in square brackets, like [1] or [2]. "
    f'If the sources do not contain the answer, reply exactly: "{NOT_COVERED}" '
    "Do not use outside knowledge. Keep the answer under 150 words."
)


@dataclass
class Answer:
    text: str
    sources: list[Hit]  # the chunks that were given to the model, in order [1], [2], ...
    cited: list[int]    # the source numbers the answer actually cites
    tokens: int


def body_of(hit: Hit) -> str:
    """The stored text starts with the heading and a blank line; return only the text after it."""
    return hit.text.split("\n\n", 1)[-1]


def build_prompt(question: str, hits: list[Hit]) -> str:
    """Number each source, put them all above the question."""
    blocks = [f"[{number}] {hit.heading}\n{body_of(hit)}" for number, hit in enumerate(hits, start=1)]
    sources = "\n\n".join(blocks)
    return f"SOURCES:\n\n{sources}\n\nQUESTION: {question}"


def cited_numbers(text: str, how_many: int) -> list[int]:
    """Find the [n] citations in the answer, keeping only numbers of real sources."""
    found = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
    return sorted(n for n in found if 1 <= n <= how_many)


def answer(question: str, check: str | None = None, k: int = 4) -> Answer:
    hits = search(question, k=k, check=check)  # step 1: RETRIEVE
    if not hits:
        return Answer(text=NOT_COVERED, sources=[], cited=[], tokens=0)

    prompt = build_prompt(question, hits)      # step 2: AUGMENT the prompt with the sources
    reply = ask(prompt, system=SYSTEM)         # step 3: GENERATE the answer
    return Answer(
        text=reply.text,
        sources=hits,
        cited=cited_numbers(reply.text, len(hits)),
        tokens=reply.prompt_tokens + reply.completion_tokens,
    )
