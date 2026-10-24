"""The agent's NODES: one function per step.

Each node receives the whole notebook (the state) and returns ONLY the parts it changes.
Nodes never touch our database or the diary; the scan runner does that between nodes.
"""

from dataclasses import asdict

from breakmyapi.agent.state import PlannedTest, ScanState, Source
from breakmyapi.checks import CHECKS, FIRST_FOUR
from breakmyapi.rag import search as library
from breakmyapi.spec.parser import parse_endpoints

GUIDANCE_PER_CHECK = 3  # how many library chunks to keep per check type


# ---- 1. read: the spec -> a list of endpoints and their shape ----


def read(state: ScanState) -> dict:
    endpoints = [asdict(e) for e in parse_endpoints(state["spec"])]  # dataclass -> plain dict
    return {"endpoints": endpoints}


# ---- 2. retrieve: what does the OWASP library say about each check type? ----


def retrieve(state: ScanState) -> dict:
    """One library search per check type, filtered to that check's documents (RAG, Lesson 22+).

    The chunks we keep are used twice: plan only plans checks that HAVE guidance, and the
    report cites them as sources.
    """
    guidance: dict[str, list[Source]] = {}
    for check_id in FIRST_FOUR:
        hits = library.search(CHECKS[check_id].catches, k=GUIDANCE_PER_CHECK, check=check_id)
        guidance[check_id] = [Source(chunk_id=h.chunk_id, heading=h.heading, url=h.url) for h in hits]
    return {"guidance": guidance}


# ---- 3. plan: which checks fit which endpoint? ----


def checks_for(endpoint: dict) -> list[str]:
    """The endpoint's SHAPE decides which checks make sense for it."""
    checks = []
    if endpoint["has_path_id"]:
        checks.append("object_level_access")  # /notes/{id}: could someone else's id work?
    if endpoint["requires_auth"]:
        checks.append("missing_auth")         # needs a login: does it really refuse without one?
    if endpoint["accepts_body"] and endpoint["method"] in ("POST", "PUT", "PATCH"):
        checks.append("mass_assignment")      # takes a body: are extra fields like role ignored?
    if endpoint["method"] == "GET":
        checks.append("excessive_data")       # returns data: does it return too much?
    return checks


def plan(state: ScanState) -> dict:
    tests: list[PlannedTest] = []
    for endpoint in state["endpoints"]:
        for check_id in checks_for(endpoint):
            if not state["guidance"].get(check_id):
                continue  # no guidance retrieved for this check: don't plan it (plan only from sources)
            tests.append(
                PlannedTest(
                    key=f"{check_id}:{endpoint['method']} {endpoint['path']}",
                    check=check_id,
                    method=endpoint["method"],
                    path=endpoint["path"],
                )
            )
    return {"plan": tests}


# ---- 4. execute and 5. judge: one planned test per run (placeholders for now) ----


def execute(state: ScanState) -> dict:
    """Takes the NEXT planned test off the list. Placeholder: it sends nothing yet.

    Each real check (next lessons) will run here, one test per run, through the SSRF-guarded
    client, and skip any test whose key is already in results (so a re-run never repeats one).
    """
    test, rest = state["plan"][0], state["plan"][1:]
    done = {r["key"] for r in state["results"]}
    if test["key"] in done:
        return {"plan": rest}  # already ran before a crash: skip it
    result = {**test, "outcome": "not_run", "note": "this check is not built yet"}
    return {"plan": rest, "results": state["results"] + [result]}


def judge(state: ScanState) -> dict:
    """Decides pass / fail for the test execute just ran. Placeholder: nothing to judge yet."""
    return {}


def after_judge(state: ScanState) -> str:
    """The loop: more tests waiting -> execute again; none left -> report."""
    return "execute" if state["plan"] else "report"


def after_plan(state: ScanState) -> str:
    """An empty plan (nothing to test) goes straight to the report."""
    return "execute" if state["plan"] else "report"


# ---- 6. report ----


def report(state: ScanState) -> dict:
    results = state["results"]
    not_run = sum(r["outcome"] == "not_run" for r in results)
    sources = {s["url"] for chunks in state["guidance"].values() for s in chunks}
    text = (
        f"{len(state['endpoints'])} endpoints, {len(results)} tests planned, "
        f"{not_run} not run yet (checks are not built yet), {len(sources)} library sources"
    )
    return {"report": text}
