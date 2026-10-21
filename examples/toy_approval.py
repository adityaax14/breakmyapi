"""Interrupts: a LangGraph run that pauses and waits for a person to say yes or no.

Safe tasks run on their own. A task that changes something in the outside world
("publish the post") pauses the graph until someone approves or rejects it.

Run these one after another (Postgres must be running):
  uv run python examples/toy_approval.py start     <- runs until it needs approval, then pauses
  uv run python examples/toy_approval.py status    <- shows what it is waiting for
  uv run python examples/toy_approval.py approve   <- continues, and does the task
  uv run python examples/toy_approval.py reject    <- (instead of approve) continues, but skips it
"""

import sys
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from breakmyapi.config import get_settings

THREAD_ID = "toy-approval-1"
CONFIG = {"configurable": {"thread_id": THREAD_ID}}
NEEDS_APPROVAL = {"publish the post"}  # tasks that change something outside the program


class State(TypedDict):
    todo: list[str]
    done: list[str]
    skipped: list[str]


def plan(state: State) -> dict:
    print("  plan:   3 tasks")
    return {"todo": ["write the draft", "check the spelling", "publish the post"]}


def work(state: State) -> dict:
    task = state["todo"][0]
    rest = state["todo"][1:]

    if task in NEEDS_APPROVAL:
        print(f"  work:   '{task}' needs approval")
        approved = interrupt({"question": f"OK to '{task}'?"})  # PAUSE here until someone answers
        if not approved:
            print(f"  work:   skipped '{task}' (rejected)")
            return {"todo": rest, "skipped": state["skipped"] + [task]}

    print(f"  work:   finished '{task}'")
    return {"todo": rest, "done": state["done"] + [task]}


def report(state: State) -> dict:
    print(f"  report: done {state['done']}, skipped {state['skipped']}")
    return {}


def more_work(state: State) -> str:
    return "work" if state["todo"] else "report"


builder = StateGraph(State)
builder.add_node("plan", plan)
builder.add_node("work", work)
builder.add_node("report", report)
builder.add_edge(START, "plan")
builder.add_edge("plan", "work")
builder.add_conditional_edges("work", more_work, ["work", "report"])
builder.add_edge("report", END)


def connection_string() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"

    with PostgresSaver.from_conn_string(connection_string()) as saver:
        saver.setup()
        graph = builder.compile(checkpointer=saver)  # interrupts need a checkpointer

        if command == "start":
            saver.delete_thread(THREAD_ID)
            graph.invoke({"todo": [], "done": [], "skipped": []}, CONFIG)
        elif command == "approve":
            graph.invoke(Command(resume=True), CONFIG)   # the answer "yes" goes back into interrupt()
        elif command == "reject":
            graph.invoke(Command(resume=False), CONFIG)  # the answer "no"

        saved = graph.get_state(CONFIG)
        if saved.interrupts:
            print(f"PAUSED, waiting for an answer to: {saved.interrupts[0].value['question']}")
        else:
            print(f"FINISHED (next step: {saved.next})")


if __name__ == "__main__":
    main()
