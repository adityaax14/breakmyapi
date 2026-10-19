"""A toy LangGraph graph with the same SHAPE as our future scanning agent, doing fake work.

No HTTP requests and no AI calls: it only shows how LangGraph works.
Run:  uv run python examples/toy_graph.py
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


# 1. THE STATE: the shared notebook every step reads from and writes to.
class ScanState(TypedDict):
    endpoints: list[str]  # what we found to test
    plan: list[str]       # tests still waiting to run
    results: list[str]    # what each finished test found
    report: str           # the final summary


# 2. THE NODES: one function per step. Each reads the notebook and returns ONLY what it changes.
def read(state: ScanState) -> dict:
    endpoints = ["GET /notes/{note_id}", "PATCH /users/me"]  # pretend we parsed a spec
    return {"endpoints": endpoints}


def plan(state: ScanState) -> dict:
    tests = [f"check {endpoint}" for endpoint in state["endpoints"]]
    return {"plan": tests}


def execute(state: ScanState) -> dict:
    current = state["plan"][0]  # take the first waiting test
    return {
        "plan": state["plan"][1:],                       # remove it from the waiting list
        "results": state["results"] + [f"{current}: ok"],  # add a (fake) result
    }


def report(state: ScanState) -> dict:
    return {"report": f"{len(state['results'])} tests run, all ok"}


# 3. THE DECISION: after execute, where do we go next?
def tests_left(state: ScanState) -> str:
    return "execute" if state["plan"] else "report"


# 4. THE GRAPH: connect the nodes with edges.
builder = StateGraph(ScanState)
builder.add_node("read", read)
builder.add_node("plan", plan)
builder.add_node("execute", execute)
builder.add_node("report", report)

builder.add_edge(START, "read")                       # always start at read
builder.add_edge("read", "plan")                      # read -> plan, always
builder.add_edge("plan", "execute")                   # plan -> execute, always
builder.add_conditional_edges("execute", tests_left, ["execute", "report"])  # loop or finish
builder.add_edge("report", END)                       # report is the last step

graph = builder.compile()


if __name__ == "__main__":
    print("=== the graph, as a diagram (Mermaid text) ===")
    print(graph.get_graph().draw_mermaid())

    start = {"endpoints": [], "plan": [], "results": [], "report": ""}

    print("=== running it, one step at a time ===")
    for step in graph.stream(start, stream_mode="updates"):
        for node, changes in step.items():
            print(f"{node:<8} changed {changes}")

    print("\n=== the final notebook ===")
    print(graph.invoke(start))
