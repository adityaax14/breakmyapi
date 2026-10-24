"""Tests for the agent graph: planning rules, a full run, resuming after a crash, and big specs.

The library search is faked in conftest.py, so no embedding model or pgvector is needed.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from breakmyapi.agent import nodes
from breakmyapi.agent.graph import build_graph
from breakmyapi.agent.state import initial_state
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.scan_runner import run_scan
from sqlalchemy import select

# 3 endpoints: GET /notes, GET /notes/{note_id}, PATCH /notes/{note_id}; all need a login.
SPEC = {
    "security": [{"bearerAuth": []}],
    "paths": {
        "/notes": {"get": {}},
        "/notes/{note_id}": {"get": {}, "patch": {"requestBody": {}}},
        "/login": {"post": {"security": [], "requestBody": {}}},
    },
}


def endpoint(method, path, has_path_id=False, requires_auth=True, accepts_body=False):
    return {"method": method, "path": path, "has_path_id": has_path_id,
            "requires_auth": requires_auth, "accepts_body": accepts_body, "is_admin": False}


# ---- planning rules ----


def test_the_endpoints_shape_decides_the_checks():
    assert nodes.checks_for(endpoint("GET", "/notes/{id}", has_path_id=True)) == [
        "object_level_access", "missing_auth", "excessive_data"]
    assert nodes.checks_for(endpoint("PATCH", "/me", accepts_body=True)) == ["missing_auth", "mass_assignment"]
    assert nodes.checks_for(endpoint("POST", "/login", requires_auth=False, accepts_body=True)) == ["mass_assignment"]


def test_plan_only_plans_checks_that_have_library_guidance():
    state = initial_state(SPEC) | {
        "endpoints": [endpoint("GET", "/notes")],
        "guidance": {"missing_auth": [{"chunk_id": "c", "heading": "h", "url": "u"}], "excessive_data": []},
    }
    planned = nodes.plan(state)["plan"]
    assert [t["check"] for t in planned] == ["missing_auth"]  # excessive_data had no sources
    assert planned[0]["key"] == "missing_auth:GET /notes"


# ---- a whole run ----


def run_graph(spec, checkpointer=None, config=None):
    return build_graph(checkpointer).invoke(initial_state(spec), config)


def test_a_full_run_plans_and_reports_without_sending_anything(db):
    final = run_graph(SPEC)
    assert len(final["endpoints"]) == 4
    # GET /notes: missing_auth, excessive_data | GET /notes/{id}: +object_level_access
    # PATCH /notes/{id}: object_level_access, missing_auth, mass_assignment | POST /login: mass_assignment
    assert len(final["plan"]) == 0                 # every planned test was taken off the list...
    assert len(final["results"]) == 9              # ...and has exactly one result
    assert {r["outcome"] for r in final["results"]} == {"not_run"}  # placeholders: nothing sent yet
    assert final["report"].startswith("4 endpoints, 9 tests planned")


def test_execute_never_runs_the_same_test_twice():
    test = {"key": "missing_auth:GET /notes", "check": "missing_auth", "method": "GET", "path": "/notes"}
    state = initial_state(SPEC) | {"plan": [test], "results": [test | {"outcome": "pass", "note": "earlier"}]}
    changes = nodes.execute(state)
    assert changes == {"plan": []}  # skipped: no second result


# ---- crash and resume (the checkpointer) ----


def test_a_crashed_run_resumes_where_it_stopped(db, monkeypatch):
    calls = {"n": 0}
    real_execute = nodes.execute

    def execute_that_crashes_once(state):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("the worker died here")  # during the 4th test
        return real_execute(state)

    monkeypatch.setattr(nodes, "execute", execute_that_crashes_once)  # before build_graph reads it
    saver, config = InMemorySaver(), {"configurable": {"thread_id": "scan-1"}}
    graph = build_graph(saver)

    with pytest.raises(RuntimeError):
        graph.invoke(initial_state(SPEC), config)
    saved = graph.get_state(config)
    assert saved.next == ("execute",)          # it knows exactly where it stopped
    assert len(saved.values["results"]) == 3   # with the 3 tests that finished

    final = graph.invoke(None, config)         # None = continue the saved run
    keys = [r["key"] for r in final["results"]]
    assert len(keys) == 9 and len(set(keys)) == 9  # all 9 done, none twice
    assert calls["n"] == 10                         # 3 + the crash + 6 more: nothing was redone


# ---- through the scan runner ----


def diary(db, scan_id):
    with db() as session:
        return session.scalars(select(ScanEvent.message).where(ScanEvent.scan_id == scan_id).order_by(ScanEvent.id)).all()


def add_scan(db, user_id, spec):
    with db() as session:
        scan = Scan(target_url="http://localhost:8001", spec=spec, user_id=user_id)
        session.add(scan)
        session.commit()
        return scan.id


def test_the_scan_diary_shows_each_step(db, priya):
    scan_id = add_scan(db, priya.user_id, SPEC)
    run_scan(scan_id)
    lines = diary(db, scan_id)
    assert lines[0] == "scan started"
    assert lines[1] == "read the spec: 4 endpoints"
    assert lines[2] == "found 12 OWASP library sections for 4 check types"
    assert lines[3] == "planned 9 tests"
    assert "missing_auth on GET /notes: this check is not built yet" in lines
    assert lines[-1] == "scan completed"


def test_a_big_spec_fits_within_our_step_limit(db, priya):
    # 30 endpoints x 2 checks = 60 tests = 120+ steps.
    big = {"security": [{"bearerAuth": []}], "paths": {f"/things{i}": {"get": {}} for i in range(30)}}
    scan_id = add_scan(db, priya.user_id, big)
    run_scan(scan_id)
    assert "planned 60 tests" in diary(db, scan_id)
    assert diary(db, scan_id)[-1] == "scan completed"


def test_a_loop_that_never_ends_is_stopped(db, priya, monkeypatch):
    # A bug: execute never takes the test off the list, so execute -> judge -> execute ... forever.
    calls = {"n": 0}

    def stuck_execute(state):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(nodes, "execute", stuck_execute)
    scan_id = add_scan(db, priya.user_id, SPEC)
    run_scan(scan_id)
    assert diary(db, scan_id)[-1] == "scan failed"
    assert calls["n"] < 120  # stopped by OUR limit (210 steps), not LangGraph's default (10,007)


def test_a_spec_needing_too_many_tests_fails_clearly(db, priya):
    huge = {"security": [{"bearerAuth": []}], "paths": {f"/things{i}": {"get": {}} for i in range(60)}}
    scan_id = add_scan(db, priya.user_id, huge)  # 120 tests > MAX_TESTS (100)
    run_scan(scan_id)
    lines = diary(db, scan_id)
    assert lines[-1] == "scan failed"
    assert not any("not built yet" in line for line in lines)  # stopped before running any test
