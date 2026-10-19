"""Measure how well search finds the right chunks, using corpus/retrieval_questions.yaml.

Run from the project folder (Postgres must be running):
  uv run python -m breakmyapi.rag.eval_retrieval
"""

import json
import sys

import yaml

from breakmyapi.rag.chunk import CHUNKS_FILE
from breakmyapi.rag.fetch_corpus import CORPUS_DIR
from breakmyapi.rag.search import search

K = 3  # how many results we look at per question

# Three ways of searching, measured side by side. Each one adds one improvement.
SETTINGS = {
    "plain": {"instruction": False, "use_check": False},
    "+ instruction": {"instruction": True, "use_check": False},
    "+ check filter": {"instruction": False, "use_check": True},
    "+ instruction + check filter": {"instruction": True, "use_check": True},
}


def load_questions() -> list[dict]:
    text = (CORPUS_DIR / "retrieval_questions.yaml").read_text(encoding="utf-8")
    questions = yaml.safe_load(text)["questions"]

    # Catch typos in the answer key: every "relevant" id must be a real chunk id.
    with CHUNKS_FILE.open(encoding="utf-8") as f:
        real_ids = {json.loads(line)["id"] for line in f}
    for q in questions:
        unknown = set(q["relevant"]) - real_ids
        if unknown:
            raise ValueError(f"unknown chunk ids {sorted(unknown)} in question: {q['question']}")
    return questions


def first_correct_rank(question: dict, setting: dict) -> int | None:
    """1 if the top result is correct, 2 if the second is, ... None if none of the top K is."""
    hits = search(
        question["question"],
        k=K,
        instruction=setting["instruction"],
        check=question["check"] if setting["use_check"] else None,
    )
    for rank, hit in enumerate(hits, start=1):
        if hit.chunk_id in question["relevant"]:
            return rank
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    questions = load_questions()
    print(f"{len(questions)} questions, looking at the top {K} results of each\n")
    print(f"{'setting':<32}{'hit@1':>7}{'hit@3':>7}")

    for name, setting in SETTINGS.items():
        ranks = [first_correct_rank(q, setting) for q in questions]
        hit_at_1 = sum(1 for r in ranks if r == 1) / len(ranks)
        hit_at_k = sum(1 for r in ranks if r is not None) / len(ranks)
        print(f"{name:<32}{hit_at_1:>7.0%}{hit_at_k:>7.0%}")
        for q, r in zip(questions, ranks):
            if r is None:
                print(f"      missed: {q['question']}")


if __name__ == "__main__":
    main()
