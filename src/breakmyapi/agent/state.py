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


class ReportSection(TypedDict):
    check: str                 # e.g. "missing_auth"
    name: str                  # e.g. "Missing auth"
    counts: dict[str, int]     # e.g. {"not_run": 3, "skipped": 1}
    endpoints: list[str]       # e.g. ["GET /notes", "PATCH /notes/{note_id}"]
    advice: str | None         # the AI's fix advice, citing sources as [1], [2]; None if unavailable
    sources: list[dict]        # numbered sources: {"n": 1, "heading": ..., "url": ..., "cited": True}
    note: str                  # anything the reader should know, e.g. why advice is missing


class ScanState(TypedDict):
    spec: dict                          # the OpenAPI spec (input)
    target_url: str                     # the running API to test (input); execute sends requests here
    test_token: str | None              # optional (input): a login token for a throwaway test account
    framework: str                      # the user's framework (input), e.g. "fastapi"; fixes are written for it
    endpoints: list[dict]               # filled by read
    guidance: dict[str, list[Source]]   # filled by retrieve: check id -> library chunks about it
    plan: list[PlannedTest]             # filled by plan; execute takes them off one by one
    approval: str                       # filled by approve: "not_needed", "approved" or "rejected"
    results: list[TestResult]           # filled by execute/judge, one per finished test
    report: str                         # filled by report: a one-line summary
    sections: list[ReportSection]       # filled by report: one section per check type tested


def initial_state(spec: dict, framework: str = "generic", target_url: str = "",
                   test_token: str | None = None) -> ScanState:
    return {"spec": spec, "target_url": target_url, "test_token": test_token, "framework": framework,
            "endpoints": [], "guidance": {}, "plan": [], "approval": "", "results": [], "report": "",
            "sections": []}
