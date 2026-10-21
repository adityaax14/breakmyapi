"""Tests for POST /library/ask: input checks and error handling, without Postgres or the LLM."""

from fastapi.testclient import TestClient

import breakmyapi.api.main as main
from breakmyapi.llm.client import LLMConfigError

client = TestClient(main.app)


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
