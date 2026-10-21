"""Checkpoints: a LangGraph run that survives a crash.

After every step, LangGraph saves the notebook (the state) into Postgres. If the program
crashes halfway, running it again with the same thread_id continues from the last finished
step instead of starting over.

Run these one after another (Postgres must be running):
  uv run python examples/toy_checkpoints.py start     <- crashes on purpose at "task 3"
  uv run python examples/toy_checkpoints.py history   <- shows the saved checkpoints
  uv run python examples/toy_checkpoints.py resume    <- continues where it stopped
"""

import sys
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from breakmyapi.config import get_settings

THREAD_ID = "toy-run-1"
CONFIG = {"configurable": {"thread_id": THREAD_ID}}  # which saved run we are talking about
CRASH = {"enabled": False}                           # the "start" command switches this on


class State(TypedDict):
    todo: list[str]
    done: list[str]


def plan(state: State) -> dict:
    print("  plan:   making 4 tasks")
    return {"todo": ["task 1", "task 2", "task 3", "task 4"]}


def work(state: State) -> dict:
    task = state["todo"][0]
    if CRASH["enabled"] and task == "task 3":
        raise RuntimeError(f"simulated crash while doing {task}")
    print(f"  work:   finished {task}")
    return {"todo": state["todo"][1:], "done": state["done"] + [task]}


def report(state: State) -> dict:
    print(f"  report: {len(state['done'])} tasks done")
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
    # LangGraph's saver talks to Postgres with plain psycopg, which wants "postgresql://",
    # not SQLAlchemy's "postgresql+psycopg://" that DATABASE_URL uses.
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"

    with PostgresSaver.from_conn_string(connection_string()) as saver:
        saver.setup()  # creates the checkpoint tables the first time; does nothing afterwards
        graph = builder.compile(checkpointer=saver)

        if command == "start":
            saver.delete_thread(THREAD_ID)  # forget any earlier run, start clean
            CRASH["enabled"] = True
            try:
                graph.invoke({"todo": [], "done": []}, CONFIG)
            except RuntimeError as error:
                print(f"  CRASHED: {error}")

        elif command == "resume":
            graph.invoke(None, CONFIG)  # None = "no new input, continue from the last checkpoint"

        elif command == "history":
            for snapshot in graph.get_state_history(CONFIG):  # newest first
                print(f"  step {snapshot.metadata['step']:>2}   next: {snapshot.next!s:<12} "
                      f"done: {snapshot.values.get('done')}")

        saved = graph.get_state(CONFIG)
        print(f"saved now -> done: {saved.values.get('done')}, todo: {saved.values.get('todo')}, "
              f"next step: {saved.next}")


if __name__ == "__main__":
    main()
