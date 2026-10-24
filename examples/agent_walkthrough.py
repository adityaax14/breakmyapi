"""Watch the real agent graph work, one station at a time.

It runs the REAL graph from src/breakmyapi/agent/ on the sample spec, and prints what each
node changed. The library search is replaced by a pretend one, so no database is needed.
Run:  uv run python examples/agent_walkthrough.py
"""

import json
import sys

import yaml

from breakmyapi.agent.graph import build_graph
from breakmyapi.agent.state import initial_state
from breakmyapi.rag import search as library
from breakmyapi.rag.search import Hit

sys.stdout.reconfigure(encoding="utf-8")


def pretend_search(question, k=3, check=None, **kwargs):
    return [Hit(chunk_id=f"{check}-{i}", heading=f"({check} section {i})",
                url=f"https://owasp.example/{check}", score=1.0, text="") for i in range(k)]


library.search = pretend_search  # the retrieve node calls library.search, so it now gets ours

spec = yaml.safe_load(open("docs/sample-spec.yaml", encoding="utf-8"))
graph = build_graph()

step = 0
for update in graph.stream(initial_state(spec), stream_mode="updates"):
    for node, changes in update.items():
        step += 1
        print(f"\n===== step {step}: {node} =====")
        if not changes:
            print("(changed nothing)")
            continue
        for field, value in changes.items():
            if field == "guidance":  # long: show just the size of each list
                value = {check: f"{len(chunks)} sections" for check, chunks in value.items()}
            if field in ("plan", "results") and len(value) > 3:
                shown = json.dumps(value[:2], indent=2)
                print(f"{field}: ({len(value)} items, first 2 shown)\n{shown}")
                continue
            print(f"{field}: {json.dumps(value, indent=2)}")
