"""Shared test helpers. pytest loads this file by itself; any test can ask for `db` by name.

`db` is a throwaway SQLite database that lives in memory, so tests need no Postgres
(CI has none). Each test that asks for it gets a fresh, empty one.
"""

import uuid
from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import breakmyapi.api.main as main
import breakmyapi.scan_runner as scan_runner
from breakmyapi.db import get_session
from breakmyapi.models import Base
from breakmyapi.agent import verifiers
from breakmyapi.rag import answer as advisor
from breakmyapi.rag import search as library
from breakmyapi.rag.answer import Answer
from breakmyapi.rag.search import Hit


def fake_library_search(question, k=3, check=None, **kwargs):
    """Stands in for the real OWASP library search (no embedding model, no pgvector needed)."""
    return [
        Hit(chunk_id=f"{check}-{i}", heading=f"{check} section {i}", url=f"https://owasp.example/{check}",
            score=1.0, text="...")
        for i in range(k)
    ]


def fake_advice(question, check=None, k=4):
    """Stands in for the real RAG answer (no embedding model, no database, no LLM call, no cost)."""
    hits = fake_library_search(question, k=2, check=check)
    return Answer(text=f"Advice for {check} [1].", sources=hits, cited=[1], tokens=0)


@pytest.fixture
def db(monkeypatch):
    # StaticPool: every session shares ONE connection, so they all see the same in-memory database.
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(engine, expire_on_commit=False)

    def test_session():
        with TestSession() as session:
            yield session

    main.app.dependency_overrides[get_session] = test_session   # the API uses the test database
    monkeypatch.setattr(scan_runner, "SessionLocal", TestSession)  # and so does the worker code

    # The agent's checkpoints go to memory instead of Postgres (one saver per test, shared by
    # all runs in that test, so a test can "crash" and resume).
    saver = InMemorySaver()

    @contextmanager
    def memory_checkpointer():
        yield saver

    monkeypatch.setattr(scan_runner, "checkpointer", memory_checkpointer)
    monkeypatch.setattr(library, "search", fake_library_search)
    monkeypatch.setattr(advisor, "answer", fake_advice)
    # The agent-flow tests check the plumbing, not the checks, and must never touch the network.
    # So verifiers stay as placeholders here; the real ones are tested in test_verifiers.py.
    monkeypatch.setattr(verifiers, "run_test",
                        lambda target_url, test, test_token=None: ("not_run", "this check is not built yet"))
    yield TestSession
    main.app.dependency_overrides.clear()


def logged_in_client(email: str) -> TestClient:
    """A test browser that has signed up and sends its login token on every request."""
    client = TestClient(main.app)
    body = client.post("/auth/signup", json={"email": email, "password": "long enough password"}).json()
    client.headers["Authorization"] = f"Bearer {body['token']}"
    client.user_id = uuid.UUID(body["user"]["id"])
    return client


@pytest.fixture
def priya(db):
    return logged_in_client("priya@example.com")


@pytest.fixture
def rahul(db):
    """A second user, to check that people cannot see or touch each other's things."""
    return logged_in_client("rahul@example.com")
