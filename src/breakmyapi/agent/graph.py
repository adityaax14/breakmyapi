"""The agent's GRAPH: the nodes, connected by edges.

    START -> read -> retrieve -> plan -> approve -> execute -> judge -> report -> END
                                   |        |          ^          |
                                   |        |          +----------+   (more tests waiting: loop)
                                   |        +-> report                (everything was rejected)
                                   +-> report                         (nothing to test)

approve may PAUSE the graph (interrupt) until the user answers. That needs a checkpointer,
because the paused run must be saved somewhere to be resumed later.
Still to come: judge sending a finding back to plan for a deeper look.
"""

from langgraph.graph import END, START, StateGraph

from breakmyapi.agent import nodes
from breakmyapi.agent.state import ScanState

# The node names; each is also the name of its function in nodes.py.
STEP_NAMES = ["read", "retrieve", "plan", "approve", "execute", "judge", "report"]


def build_graph(checkpointer=None):
    builder = StateGraph(ScanState)
    for name in STEP_NAMES:
        builder.add_node(name, getattr(nodes, name))  # getattr(nodes, "read") is nodes.read

    builder.add_edge(START, "read")
    builder.add_edge("read", "retrieve")
    builder.add_edge("retrieve", "plan")
    builder.add_conditional_edges("plan", nodes.after_plan, ["approve", "report"])
    builder.add_conditional_edges("approve", nodes.after_approve, ["execute", "report"])
    builder.add_edge("execute", "judge")
    builder.add_conditional_edges("judge", nodes.after_judge, ["execute", "report"])
    builder.add_edge("report", END)

    # With a checkpointer, LangGraph saves the state after EVERY node, so a crashed run can resume.
    return builder.compile(checkpointer=checkpointer)
