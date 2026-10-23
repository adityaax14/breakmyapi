"""Measure the GENERATION half of RAG: do the answers stick to their sources?

For every question in corpus/answer_questions.yaml:
  1. refusal:      covered questions should be answered, uncovered ones refused
  2. citations:    answers should cite at least one source
  3. faithfulness: a second, stronger model (the "judge") splits the answer into claims
                   and checks each claim against the sources

Run (Postgres running, Groq key in .env):
  uv run python -m breakmyapi.rag.eval_answers
"""

import json
import sys

import yaml

from breakmyapi.llm.client import ask
from breakmyapi.rag.answer import NOT_COVERED, Answer, answer, body_of
from breakmyapi.rag.fetch_corpus import CORPUS_DIR

JUDGE_SYSTEM = (
    "You check whether an ANSWER is supported by its SOURCES. "
    "Split the answer into its separate factual claims. For each claim, decide whether the "
    "sources state it (supported: true) or not (supported: false). Judge ONLY against the "
    "sources, never against your own knowledge. Reply with JSON only, in this shape: "
    '{"claims": [{"claim": "<the claim, shortened>", "supported": true}]}'
)


def is_refusal(text: str) -> bool:
    return NOT_COVERED.lower().rstrip(".") in text.lower()


def parse_claims(text: str) -> list[dict] | None:
    """Read the judge's JSON reply. None means the reply was not usable."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        return None
    return [c for c in claims if isinstance(c, dict) and isinstance(c.get("supported"), bool)]


def judge(result: Answer) -> list[dict] | None:
    """Ask the strong model to check each claim of the answer against the numbered sources."""
    sources = "\n\n".join(f"[{n}] {body_of(hit)}" for n, hit in enumerate(result.sources, start=1))
    reply = ask(f"SOURCES:\n\n{sources}\n\nANSWER:\n{result.text}", system=JUDGE_SYSTEM, strong=True)
    return parse_claims(reply.text)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    text = (CORPUS_DIR / "answer_questions.yaml").read_text(encoding="utf-8")
    questions = yaml.safe_load(text)["questions"]

    refusals_right = 0
    answered = cited = 0
    supported = total_claims = judge_failures = 0

    for q in questions:
        result = answer(q["question"], check=q["check"])
        refused = is_refusal(result.text)
        right = refused != q["covered"]  # covered -> should NOT refuse; uncovered -> should refuse
        refusals_right += right
        print(f"\n{'OK ' if right else 'BAD'} {'refused ' if refused else 'answered'}  {q['question']}")

        if refused or not q["covered"]:
            continue
        answered += 1
        cited += bool(result.cited)

        claims = judge(result)
        if claims is None:
            judge_failures += 1
            print("    judge reply unusable")
            continue
        for claim in claims:
            total_claims += 1
            supported += claim["supported"]
            if not claim["supported"]:
                print(f"    NOT IN SOURCES: {claim.get('claim', '')}")
        print(f"    {sum(c['supported'] for c in claims)}/{len(claims)} claims supported, cites {result.cited}")

    print("\n" + "=" * 70)
    print(f"refusals right:   {refusals_right}/{len(questions)}")
    print(f"answers citing:   {cited}/{answered}")
    if total_claims:
        print(f"faithfulness:     {supported}/{total_claims} claims supported ({supported / total_claims:.0%})")
    print(f"judge failures:   {judge_failures}")


if __name__ == "__main__":
    main()
