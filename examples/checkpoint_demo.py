"""See checkpoints with your own eyes: crash the REAL agent graph on purpose, then resume it.

Uses the real graph and the real Postgres checkpointer (Postgres must be running: docker compose up -d).
The library search is replaced by a pretend one, so no embedding model is needed.
Run:  uv run python examples/checkpoint_demo.py
"""

import sys

import yaml

from breakmyapi.agent import nodes
from breakmyapi.agent.graph import build_graph
from breakmyapi.agent.state import initial_state
from breakmyapi.rag import search as library
from breakmyapi.rag.search import Hit
from breakmyapi.scan_runner import checkpointer

sys.stdout.reconfigure(encoding="utf-8")
library.search = lambda q, k=3, check=None, **kw: [
    Hit(chunk_id=f"{check}-{i}", heading="", url=f"https://owasp.example/{check}", score=1.0, text="")
    for i in range(k)
]

# Make execute crash on its 4th call, like a worker dying in the middle of a scan.
real_execute = nodes.execute
calls = {"n": 0, "crash": True}


def execute_that_crashes(state):
    calls["n"] += 1
    if calls["crash"] and calls["n"] == 4:
        raise RuntimeError("💥 the worker died while running test #4")
    return real_execute(state)


nodes.execute = execute_that_crashes  # must happen BEFORE build_graph reads nodes.execute

THREAD = "demo-scan"  # in real scans this is the scan's id
config = {"configurable": {"thread_id": THREAD}}
spec = yaml.safe_load(open("docs/sample-spec.yaml", encoding="utf-8"))


def show(title, snapshot):
    v = snapshot.values
    print(f"{title}\n   next station : {snapshot.next or '(none: finished)'}"
          f"\n   to-do (plan) : {len(v.get('plan', []))} tests"
          f"\n   done (results): {len(v.get('results', []))} tests\n")


with checkpointer() as saver:
    saver.delete_thread(THREAD)  # forget any earlier demo run
    graph = build_graph(saver)

    print("── RUN 1: start a fresh scan ──")
    try:
        graph.invoke(initial_state(spec), config)
    except RuntimeError as e:
        print(f"   {e}\n")

    show("── What Postgres remembers right after the crash ──", graph.get_state(config))

    print("── RUN 2: the worker restarts and resumes (input = None) ──")
    calls["crash"] = False
    final = graph.invoke(None, config)  # None = continue the saved run
    show("── After resuming ──", graph.get_state(config))

    keys = [r["key"] for r in final["results"]]
    print(f"execute was called {calls['n']} times in total for {len(keys)} tests "
          f"({len(set(keys))} different): nothing was redone.\n")

    print("── The photo album (newest first), as LangGraph keeps it ──")
    for snap in graph.get_state_history(config):
        print(f"   step {snap.metadata['step']:>3}  next={str(snap.next):<14} "
              f"plan={len(snap.values.get('plan', [])):>2}  results={len(snap.values.get('results', [])):>2}")
