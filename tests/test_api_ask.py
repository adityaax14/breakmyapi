"""Tests for POST /library/ask: input checks, error handling and the daily limit,
without Postgres or the LLM."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import breakmyapi.api.main as main
import breakmyapi.limits as limits
from breakmyapi.llm.client import LLMConfigError

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fake_counter(monkeypatch):
    """Every test here gets a fake usage counter instead of the Postgres one.

    `used` is what the fake returns; a test can change it to pretend the client is over the limit.
    """
    state = {"used": 1}
    monkeypatch.setattr(limits, "count_use", lambda session, key, day: state["used"])
    return state


def test_too_short_question_is_rejected():
    assert client.post("/library/ask", json={"question": "hi"}).status_code == 422


def test_unknown_check_is_rejected():
    response = client.post("/library/ask", json={"question": "what is mass assignment?", "check": "nope"})
    assert response.status_code == 422


def test_model_problems_become_503(monkeypatch):
    def broken_answer(question, check=None):
        raise LLMConfigError("LLM_API_KEY is empty")

    # Swap the real answer() for one that fails like a missing key would.
    monkeypatch.setattr(main, "answer", broken_answer)
    response = client.post("/library/ask", json={"question": "what is mass assignment?"})
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_over_the_daily_limit_gets_429_and_never_calls_the_model(monkeypatch, fake_counter):
    fake_counter["used"] = main.get_settings().ask_daily_limit + 1  # one more than allowed

    def must_not_run(question, check=None):
        raise AssertionError("the model was called although the client is over the limit")

    monkeypatch.setattr(main, "answer", must_not_run)
    response = client.post("/library/ask", json={"question": "what is mass assignment?"})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_seconds_until_tomorrow():
    assert limits.seconds_until_tomorrow(datetime(2026, 10, 22, 23, 59, 0, tzinfo=UTC)) == 60
    assert limits.seconds_until_tomorrow(datetime(2026, 10, 22, 0, 0, 0, tzinfo=UTC)) == 24 * 60 * 60
