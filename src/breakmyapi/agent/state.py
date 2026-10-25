"""The agent's STATE: the shared notebook every node reads from and writes to.

Everything in here is plain data (dicts, lists, strings), because the checkpointer saves the
whole notebook to Postgres after every node, and plain data is easy to save and load.
"""

from typing import TypedDict


class PlannedTest(TypedDict):
    key: str      # unique name of this test, e.g. "missing_auth:GET /notes"; used to never run it twice
    check: str    # which of the fixed check types, e.g. "missing_auth"
    method: str   # e.g. "GET"
    path: str     # e.g. "/notes/{note_id}"


class TestResult(TypedDict):
    key: str
    check: str
    method: str
    path: str
    outcome: str  # "not_run" for now; later "pass", "fail" or "needs_review"
    note: str     # a short human explanation


class Source(TypedDict):
    chunk_id: str
    heading: str
    url: str


class ScanState(TypedDict):
    spec: dict                          # the OpenAPI spec (input)
    endpoints: list[dict]               # filled by read
    guidance: dict[str, list[Source]]   # filled by retrieve: check id -> library chunks about it
    plan: list[PlannedTest]             # filled by plan; execute takes them off one by one
    approval: str                       # filled by approve: "not_needed", "approved" or "rejected"
    results: list[TestResult]           # filled by execute/judge, one per finished test
    report: str                         # filled by report


def initial_state(spec: dict) -> ScanState:
    return {"spec": spec, "endpoints": [], "guidance": {}, "plan": [], "approval": "",
            "results": [], "report": ""}
