"""Tests for the approve step: the agent pauses before tests that could change data, and waits for the user."""

import pytest
from sqlalchemy import select

import breakmyapi.api.main as main
from breakmyapi.agent import nodes
from breakmyapi.agent.state import initial_state
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.scan_runner import run_scan

# GET /notes (read-only) and PATCH /notes/{note_id} (changes data); both need a login.
SPEC = {"security": [{"bearerAuth": []}], "paths": {"/notes": {"get": {}}, "/notes/{note_id}": {"patch": {"requestBody": {}}}}}
READ_ONLY = {"security": [{"bearerAuth": []}], "paths": {"/notes": {"get": {}}}}


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    monkeypatch.setattr(main, "enqueue_scan", lambda scan_id: None)  # tests have no Redis queue


def add_scan(db, user_id, spec=SPEC):
    with db() as session:
        scan = Scan(target_url="http://localhost:8001", spec=spec, user_id=user_id)
        session.add(scan)
        session.commit()
        return scan.id


def diary(db, scan_id):
    with db() as session:
        return session.scalars(select(ScanEvent.message).where(ScanEvent.scan_id == scan_id).order_by(ScanEvent.id)).all()


def answer(client, scan_id, decision):
    return client.post(f"/scans/{scan_id}/approval", json={"decision": decision})


# ---- the approve node by itself ----


def test_read_only_plans_need_no_approval():
    plan = [{"key": "k", "check": "missing_auth", "method": "GET", "path": "/notes"}]
    assert nodes.approve(initial_state(READ_ONLY) | {"plan": plan}) == {"approval": "not_needed"}


def test_a_read_only_scan_never_pauses(db, priya):
    scan_id = add_scan(db, priya.user_id, READ_ONLY)
    run_scan(scan_id)
    assert "no tests change data: no approval needed" in diary(db, scan_id)
    assert priya.get(f"/scans/{scan_id}").json()["status"] == "completed"


# ---- pausing ----


def test_the_scan_pauses_and_shows_what_it_wants_to_run(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)

    scan = priya.get(f"/scans/{scan_id}").json()
    assert scan["status"] == "waiting_approval"
    keys = [t["key"] for t in scan["approval_request"]["tests"]]
    assert keys == ["object_level_access:PATCH /notes/{note_id}", "missing_auth:PATCH /notes/{note_id}",
                    "mass_assignment:PATCH /notes/{note_id}"]  # only the PATCH tests, not the GET ones
    assert not any("not built yet" in line for line in diary(db, scan_id))  # NOTHING ran before the answer


def test_approve_runs_everything(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    response = answer(priya, scan_id, "approve")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"  # back in line for a worker

    run_scan(scan_id)
    lines = diary(db, scan_id)
    assert sum(line.endswith(": this check is not built yet") for line in lines) == 5  # 2 GET tests + 3 PATCH tests
    assert lines[-1] == "scan completed"


def test_reject_skips_only_the_risky_tests(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    answer(priya, scan_id, "reject")
    run_scan(scan_id)

    lines = diary(db, scan_id)
    assert "skipped 3 tests that change data, as you chose" in lines
    ran = [line for line in lines if line.endswith(": this check is not built yet")]
    assert len(ran) == 2 and all("GET /notes" in line for line in ran)  # only the read-only tests ran
    assert lines[-1] == "scan completed"


# ---- the answer endpoint's rules ----


def test_answering_twice_is_refused(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    assert answer(priya, scan_id, "approve").status_code == 200
    assert answer(priya, scan_id, "reject").status_code == 409  # already answered: no change of mind mid-way


def test_a_scan_that_is_not_waiting_cannot_be_answered(db, priya):
    scan_id = add_scan(db, priya.user_id)  # still queued, never asked anything
    assert answer(priya, scan_id, "approve").status_code == 409


def test_only_approve_or_reject_are_accepted(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    assert answer(priya, scan_id, "maybe").status_code == 422


def test_you_cannot_answer_someone_elses_scan(db, priya, rahul):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    assert answer(rahul, scan_id, "approve").status_code == 404
    assert priya.get(f"/scans/{scan_id}").json()["status"] == "waiting_approval"  # untouched


def test_a_paused_scan_can_be_cancelled(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    assert priya.post(f"/scans/{scan_id}/cancel").json()["status"] == "cancelled"
    assert answer(priya, scan_id, "approve").status_code == 409  # too late to approve


def test_the_approve_node_does_nothing_before_it_pauses(monkeypatch):
    """When resumed, LangGraph re-runs approve from its first line. So the code before
    interrupt() must not change anything; here we check it only READS the state."""
    plan = [{"key": "k", "check": "mass_assignment", "method": "PATCH", "path": "/notes/{note_id}"}]
    state = initial_state(SPEC) | {"plan": plan}
    before = repr(state)

    def fake_interrupt(question):
        assert repr(state) == before  # nothing was changed on the way to the question
        return "approve"

    monkeypatch.setattr(nodes, "interrupt", fake_interrupt)
    assert nodes.approve(state) == {"approval": "approved"}
    assert repr(state) == before
