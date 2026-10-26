"""Tests for the report: one cited section per check type, written for the user's framework.

The RAG answer is faked in conftest.py (no model, no database, no LLM cost); some tests replace it again.
"""

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import breakmyapi.api.main as main
from breakmyapi.agent import nodes
from breakmyapi.agent.graph import build_graph
from breakmyapi.agent.state import initial_state
from breakmyapi.rag import answer as advisor
from breakmyapi.scan_runner import run_scan

# GET /notes/{note_id} (3 checks) and PATCH /notes/{note_id} (3 checks, needs approval).
SPEC = {"security": [{"bearerAuth": []}],
        "paths": {"/notes/{note_id}": {"get": {}, "patch": {"requestBody": {}}}}}


def finished_state(db, framework="generic", answer="approve"):
    graph, config = build_graph(InMemorySaver()), {"configurable": {"thread_id": "t"}}
    graph.invoke(initial_state(SPEC, framework), config)  # pauses at approve
    return graph.invoke(Command(resume=answer), config)


def test_one_section_per_planned_check_type_in_a_fixed_order(db):
    sections = finished_state(db)["sections"]
    assert [s["check"] for s in sections] == ["object_level_access", "missing_auth", "mass_assignment",
                                              "excessive_data"]
    ola = sections[0]
    assert ola["name"] == "Object-level access"
    assert ola["endpoints"] == ["GET /notes/{note_id}", "PATCH /notes/{note_id}"]
    assert ola["counts"] == {"not_run": 2}


def test_advice_has_numbered_sources_and_marks_which_were_cited(db):
    section = finished_state(db)["sections"][0]
    assert section["advice"] == "Advice for object_level_access [1]."
    assert [(s["n"], s["cited"]) for s in section["sources"]] == [(1, True), (2, False)]


def test_the_question_names_the_users_framework(db, monkeypatch):
    questions = []
    real = advisor.answer
    monkeypatch.setattr(advisor, "answer", lambda q, check=None, k=4: questions.append(q) or real(q, check, k))
    finished_state(db, framework="fastapi")
    assert all("FastAPI (Python)" in q for q in questions)
    assert len(questions) == 4  # one RAG answer per check type, not per test


def test_rejected_tests_show_up_as_skipped(db):
    sections = {s["check"]: s for s in finished_state(db, answer="reject")["sections"]}
    assert sections["mass_assignment"]["counts"] == {"skipped": 1}          # only planned on PATCH
    assert sections["missing_auth"]["counts"] == {"not_run": 1, "skipped": 1}


def test_a_model_outage_does_not_break_the_report(db, monkeypatch):
    def model_down(*args, **kwargs):
        raise ConnectionError("the LLM provider is down")

    monkeypatch.setattr(advisor, "answer", model_down)
    final = finished_state(db)
    assert len(final["sections"]) == 4  # the report is still written...
    assert all(s["advice"] is None and "unavailable" in s["note"] for s in final["sections"])  # ...honestly
    assert final["report"].endswith("fix advice for 0 of 4 check types")


def test_when_the_library_has_nothing_the_report_says_so(db, monkeypatch):
    monkeypatch.setattr(advisor, "answer", lambda q, check=None, k=4: advisor.Answer(
        text=advisor.NOT_COVERED, sources=[], cited=[], tokens=0))
    section = finished_state(db)["sections"][0]
    assert section["advice"] is None
    assert "no specific advice" in section["note"]


def test_an_unknown_framework_falls_back_to_generic():
    state = initial_state(SPEC, "cobol") | {"results": []}
    assert nodes.report(state)["sections"] == []  # no crash on a value it doesn't know


# ---- through the worker and the API ----


@pytest.fixture
def no_redis(monkeypatch):
    monkeypatch.setattr(main, "enqueue_scan", lambda scan_id: None)


def test_the_finished_report_is_saved_on_the_scan_and_returned_by_the_api(db, priya, no_redis):
    spec = "security: [{bearerAuth: []}]\npaths:\n  /notes:\n    get: {}\n"
    scan = priya.post("/scans", json={"target_url": "http://localhost:8001", "spec": spec,
                                      "framework": "express"}).json()
    run_scan(uuid.UUID(scan["id"]))  # the worker passes a UUID object, not text

    detail = priya.get(f"/scans/{scan['id']}").json()
    assert detail["status"] == "completed"
    assert detail["framework"] == "express"
    assert detail["report"]["summary"].startswith("1 endpoints, 2 tests planned")
    assert [s["check"] for s in detail["report"]["sections"]] == ["missing_auth", "excessive_data"]


def test_only_known_frameworks_are_accepted(db, priya):
    spec = "paths:\n  /notes:\n    get: {}\n"
    response = priya.post("/scans", json={"target_url": "http://localhost:8001", "spec": spec, "framework": "rails"})
    assert response.status_code == 422
