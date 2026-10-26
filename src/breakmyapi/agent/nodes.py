"""The agent's NODES: one function per step.

Each node receives the whole notebook (the state) and returns ONLY the parts it changes.
Nodes never touch our database or the diary; the scan runner does that between nodes.
"""

import traceback
from collections import Counter
from dataclasses import asdict

from langgraph.types import interrupt

from breakmyapi.agent import verifiers
from breakmyapi.agent.state import PlannedTest, ReportSection, ScanState, Source
from breakmyapi.checks import CHECKS, FIRST_FOUR
from breakmyapi.rag import answer as advisor
from breakmyapi.rag import search as library
from breakmyapi.spec.parser import parse_endpoints

# The frameworks a user can pick, and how we name them when asking the library for fixes.
FRAMEWORKS = {
    "generic": "a web API",
    "fastapi": "FastAPI (Python)",
    "django": "Django REST Framework (Python)",
    "express": "Express (Node.js)",
    "spring": "Spring Boot (Java)",
}

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


# ---- approve: ask the human before any test that could change data ----

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")  # requests that can change data on the target


def approve(state: ScanState) -> dict:
    """Pause the whole graph and ask the user, if the plan contains tests that could change data.

    interrupt(question) STOPS the graph right here. LangGraph saves a checkpoint, and the run
    ends for now. Later, someone resumes the graph with Command(resume=answer): LangGraph then
    runs this node AGAIN FROM ITS FIRST LINE, and this time interrupt(...) returns the answer
    instead of stopping. That re-run is why this node must have NO side effects before the
    interrupt: anything above it would happen twice.
    """
    risky = [t for t in state["plan"] if t["method"] in WRITE_METHODS]
    if not risky:
        return {"approval": "not_needed"}  # only read-only tests: no need to bother the user

    # The value we pass is what the user will be shown: the list of risky tests.
    answer = interrupt({"tests": risky})

    if answer == "approve":
        return {"approval": "approved"}
    # Rejected (or any unexpected answer: fail safe): drop the risky tests, keep the read-only ones,
    # and record the skipped ones so the report can say what was NOT tested and why.
    skipped = [{**t, "outcome": "skipped", "note": "skipped: you chose not to run tests that change data"}
               for t in risky]
    safe = [t for t in state["plan"] if t["method"] not in WRITE_METHODS]
    return {"approval": "rejected", "plan": safe, "results": state["results"] + skipped}


def after_approve(state: ScanState) -> str:
    """After approve: tests left -> execute; nothing left (e.g. all were rejected) -> report."""
    return "execute" if state["plan"] else "report"


# ---- 4. execute and 5. judge: one planned test per run (placeholders for now) ----


def execute(state: ScanState) -> dict:
    """Run the NEXT planned test: one test per run, through the SSRF-guarded probe.

    Idempotent: a test whose key is already in results (a re-run after a crash) is skipped,
    so a request is never sent twice.
    """
    test, rest = state["plan"][0], state["plan"][1:]
    done = {r["key"] for r in state["results"]}
    if test["key"] in done:
        return {"plan": rest}  # already ran before a crash: skip it

    outcome, note = verifiers.run_test(state["target_url"], test, state["test_token"])
    result = {**test, "outcome": outcome, "note": note}
    return {"plan": rest, "results": state["results"] + [result]}


def judge(state: ScanState) -> dict:
    """The verifier in execute already decided pass/fail. (A future lesson adds an LLM
    second opinion for the 'needs_review' cases; for now there is nothing more to decide.)"""
    return {}


def after_judge(state: ScanState) -> str:
    """The loop: more tests waiting -> execute again; none left -> report."""
    return "execute" if state["plan"] else "report"


def after_plan(state: ScanState) -> str:
    """An empty plan (nothing to test) goes straight to the report; otherwise ask for approval."""
    return "approve" if state["plan"] else "report"


# ---- 6. report ----


def fix_advice(check_id: str, framework: str) -> tuple[str | None, list[dict], str]:
    """Ask the OWASP library how to PREVENT this weakness in the user's framework.

    This is the RAG pipeline from the library lessons (search -> numbered sources in the
    prompt -> the LLM answers ONLY from them, citing [1], [2]). Returns (advice, sources, note).
    """
    # Worded with care (tested on the real model): asking "how in FastAPI?" made the model either
    # refuse (the sources are not about FastAPI) or invent FastAPI details that were wrong.
    # So: ask for the sources' prevention steps, and framework details ONLY where a source supports them.
    question = (
        f"How do I prevent this weakness: {CHECKS[check_id].catches}? "
        f"My API is built with {FRAMEWORKS[framework]}. Explain the prevention steps the sources give; "
        f"only add {FRAMEWORKS[framework]}-specific details where a source supports them."
    )
    try:
        result = advisor.answer(question, check=check_id)
    except Exception:
        # The model could be down, out of quota, or not configured. The report must still be
        # written: without advice, but with the library sources, and saying why.
        traceback.print_exc()
        return None, [], "Fix advice is unavailable right now: the AI model could not be reached."

    sources = [
        {"n": n, "heading": hit.heading, "url": hit.url, "cited": n in result.cited}
        for n, hit in enumerate(result.sources, start=1)
    ]
    if result.text.strip() == advisor.NOT_COVERED:
        return None, sources, "The OWASP library has no specific advice for this framework."
    return result.text, sources, ""


def report(state: ScanState) -> dict:
    """One section per check type that was planned: what was tested, and how to prevent it (cited)."""
    framework = state["framework"] if state["framework"] in FRAMEWORKS else "generic"
    sections: list[ReportSection] = []
    for check_id in FIRST_FOUR:  # a fixed order, so every report reads the same way
        tests = [r for r in state["results"] if r["check"] == check_id]
        if not tests:
            continue  # this check type was not planned for any endpoint
        advice, sources, note = fix_advice(check_id, framework)
        sections.append(
            ReportSection(
                check=check_id,
                name=CHECKS[check_id].name,
                counts=dict(Counter(t["outcome"] for t in tests)),  # e.g. {"not_run": 3, "skipped": 1}
                endpoints=[f"{t['method']} {t['path']}" for t in tests],
                advice=advice,
                sources=sources,
                note=note,
            )
        )

    outcomes = Counter(r["outcome"] for r in state["results"])
    with_advice = sum(s["advice"] is not None for s in sections)
    text = (
        f"{len(state['endpoints'])} endpoints, {len(state['results'])} tests planned "
        f"({outcomes['not_run']} not run yet, {outcomes['skipped']} skipped), "
        f"fix advice for {with_advice} of {len(sections)} check types"
    )
    return {"report": text, "sections": sections}
