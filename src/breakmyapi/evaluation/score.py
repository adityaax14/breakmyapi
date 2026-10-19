"""Score findings against the notes target's answer key: hits, false alarms, misses.

For now it scores the single-prompt baseline. Run:
  uv run python -m breakmyapi.evaluation.score http://localhost:8001/openapi.json
"""

import sys
from dataclasses import dataclass
from importlib.resources import files

import yaml

from breakmyapi.baselines.single_prompt import read_source, run_baseline
from breakmyapi.checks import FIRST_FOUR
from breakmyapi.spec.parser import load_spec

# One finding = (check id, "METHOD /path"), for example ("missing_auth", "GET /notes").
Finding = tuple[str, str]


def load_bugs() -> list[dict]:
    """Read the answer key that sits next to the notes target's code."""
    text = files("notes_target").joinpath("ground_truth.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["bugs"]


def expected_findings(bugs: list[dict], flags: set[str]) -> set[Finding]:
    """What a perfect scanner should report when these flags are on."""
    expected = set()
    for bug in bugs:
        if bug["flag"] in flags:
            for endpoint in bug["endpoints"]:
                expected.add((bug["check"], endpoint))
    return expected


@dataclass
class Score:
    hits: set[Finding]          # reported, and really a bug
    false_alarms: set[Finding]  # reported, but not a bug
    missed: set[Finding]        # really a bug, but not reported

    @property
    def precision(self) -> float | None:
        reported = len(self.hits) + len(self.false_alarms)
        return len(self.hits) / reported if reported else None

    @property
    def recall(self) -> float | None:
        real = len(self.hits) + len(self.missed)
        return len(self.hits) / real if real else None


def score(reported: set[Finding], expected: set[Finding]) -> Score:
    return Score(
        hits=reported & expected,
        false_alarms=reported - expected,
        missed=expected - reported,
    )


def score_by_check(reported: set[Finding], expected: set[Finding]) -> dict[str, Score]:
    results = {}
    for check_id in FIRST_FOUR:
        results[check_id] = score(
            {f for f in reported if f[0] == check_id},
            {f for f in expected if f[0] == check_id},
        )
    results["ALL"] = score(reported, expected)
    return results


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def print_report(title: str, reported: set[Finding], expected: set[Finding]) -> None:
    print(f"\n=== {title}: {len(expected)} real bugs ===")
    print(f"{'check':<22}{'hits':>6}{'false alarms':>14}{'missed':>8}{'precision':>11}{'recall':>8}")
    for name, s in score_by_check(reported, expected).items():
        print(f"{name:<22}{len(s.hits):>6}{len(s.false_alarms):>14}{len(s.missed):>8}"
              f"{percent(s.precision):>11}{percent(s.recall):>8}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m breakmyapi.evaluation.score <spec URL or file>")
    sys.stdout.reconfigure(encoding="utf-8")

    result = run_baseline(load_spec(read_source(sys.argv[1])))
    reported = {(g.check_id, f"{g.method} {g.path}") for g in result.guesses}
    print(f"Single-prompt baseline: {len(reported)} findings | {result.calls} calls | "
          f"{result.tokens} tokens | {result.unparseable} unusable replies")

    # The baseline only reads the spec, which is the same in both cases,
    # so one run can be scored against both answer keys.
    bugs = load_bugs()
    every_flag = {bug["flag"] for bug in bugs}
    print_report("Target with ALL bugs on", reported, expected_findings(bugs, every_flag))
    print_report("Target with NO bugs (safe mode)", reported, expected_findings(bugs, set()))


if __name__ == "__main__":
    main()
