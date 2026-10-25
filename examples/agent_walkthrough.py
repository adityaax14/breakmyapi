"""Watch the real agent graph work, one station at a time, including the approval pause.

It runs the REAL graph from src/breakmyapi/agent/ on the sample spec, and prints what each
node changed. The library search is replaced by a pretend one, and the checkpoints are kept
in memory, so no database is needed.
Run:  uv run python examples/agent_walkthrough.py            (answers "approve" at the pause)
      uv run python examples/agent_walkthrough.py reject     (answers "reject")
"""

import json
import sys

import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

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
answer = sys.argv[1] if len(sys.argv) > 1 else "approve"

# A pause needs somewhere to save the paused run: here, memory. (The worker uses Postgres.)
graph = build_graph(InMemorySaver())
config = {"configurable": {"thread_id": "walkthrough"}}

step = 0


def show(update):
    global step
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


start = initial_state(spec)
while True:
    paused = False
    for update in graph.stream(start, config, stream_mode="updates"):
        if "__interrupt__" in update:
            question = update["__interrupt__"][0].value
            print("\n⏸  ===== PAUSED: the agent asks before these tests =====")
            for t in question["tests"]:
                print(f"   {t['method']:6} {t['path']:20} {t['check']}")
            print(f"   (the run is saved; we answer: {answer!r})")
            paused = True
        else:
            show(update)
    if not paused:
        break
    start = Command(resume=answer)  # resume the paused run with our answer
