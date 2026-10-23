"""Shared test helpers. pytest loads this file by itself; any test can ask for `db` by name.

`db` is a throwaway SQLite database that lives in memory, so tests need no Postgres
(CI has none). Each test that asks for it gets a fresh, empty one.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import breakmyapi.api.main as main
import breakmyapi.scan_runner as scan_runner
from breakmyapi.db import get_session
from breakmyapi.models import Base


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
    monkeypatch.setattr(scan_runner.time, "sleep", lambda seconds: None)  # don't really wait 1 s per step
    yield TestSession
    main.app.dependency_overrides.clear()
