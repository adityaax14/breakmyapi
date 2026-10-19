"""Baseline 1: one prompt per endpoint. No retrieval, no requests sent, no verification.

The agent has to beat this. Run it against the notes target:
  uv run python -m breakmyapi.baselines.single_prompt http://localhost:8001/openapi.json
"""

import json
import sys
from dataclasses import dataclass, field

import httpx

from breakmyapi.checks import CHECKS, FIRST_FOUR
from breakmyapi.llm.client import ask
from breakmyapi.spec.parser import Endpoint, load_spec, parse_endpoints

SYSTEM = (
    "You are an API security reviewer. You are shown the OpenAPI definition of ONE endpoint. "
    "You cannot send requests, so judge from the definition alone. "
    "Only choose from the vulnerability types you are given. Reply with JSON only."
)
REPLY_SHAPE = '{"vulnerabilities": [{"check_id": "<one id from the list>", "reason": "<one sentence>"}]}'
MAX_SCHEMA_CHARS = 6000


@dataclass
class Guess:
    check_id: str
    method: str
    path: str
    reason: str


@dataclass
class BaselineResult:
    guesses: list[Guess] = field(default_factory=list)
    calls: int = 0
    tokens: int = 0
    unparseable: int = 0


def build_prompt(spec: dict, endpoint: Endpoint, check_ids: tuple[str, ...]) -> str:
    operation = spec["paths"][endpoint.path][endpoint.method.lower()]
    schemas = json.dumps(spec.get("components", {}).get("schemas", {}))[:MAX_SCHEMA_CHARS]
    menu = "\n".join(f"- {cid}: {CHECKS[cid].catches}" for cid in check_ids)
    return f"""Endpoint: {endpoint.method} {endpoint.path}
Facts from the spec: id in path = {endpoint.has_path_id}, requires auth = {endpoint.requires_auth}, \
accepts a body = {endpoint.accepts_body}, admin route = {endpoint.is_admin}

Operation definition:
{json.dumps(operation, indent=1)}

Schemas used by the API (may be cut short):
{schemas}

Vulnerability types to choose from:
{menu}

Reply with JSON only, in exactly this shape:
{REPLY_SHAPE}
Use an empty list if you think this endpoint has none of them."""


def parse_reply(text: str, endpoint: Endpoint, check_ids: tuple[str, ...]) -> list[Guess] | None:
    """Turn the model's reply into guesses. None means the reply was not usable JSON."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("vulnerabilities"), list):
        return None

    guesses, seen = [], set()
    for item in data["vulnerabilities"]:
        if not isinstance(item, dict):
            continue
        check_id = item.get("check_id")
        # The model's output is untrusted: keep only ids from our fixed list, once each.
        if check_id not in check_ids or check_id in seen:
            continue
        seen.add(check_id)
        guesses.append(Guess(check_id, endpoint.method, endpoint.path, str(item.get("reason", ""))))
    return guesses


def run_baseline(spec: dict, check_ids: tuple[str, ...] = FIRST_FOUR) -> BaselineResult:
    result = BaselineResult()
    for endpoint in parse_endpoints(spec):
        reply = ask(build_prompt(spec, endpoint, check_ids), system=SYSTEM)
        result.calls += 1
        result.tokens += reply.prompt_tokens + reply.completion_tokens
        guesses = parse_reply(reply.text, endpoint, check_ids)
        if guesses is None:
            result.unparseable += 1
        else:
            result.guesses.extend(guesses)
    return result


def read_source(source: str) -> str:
    """Read a spec from a URL or a file path."""
    if source.startswith("http"):
        return httpx.get(source, timeout=10).text
    with open(source, encoding="utf-8") as f:
        return f.read()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m breakmyapi.baselines.single_prompt <spec URL or file>")
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

    result = run_baseline(load_spec(read_source(sys.argv[1])))
    for g in result.guesses:
        print(f"{g.method:<7} {g.path:<18} {g.check_id:<20} {g.reason}")
    print(f"\n{len(result.guesses)} guesses | {result.calls} calls | "
          f"{result.tokens} tokens | {result.unparseable} unusable replies")


if __name__ == "__main__":
    main()
