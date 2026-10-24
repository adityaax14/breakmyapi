"""Tests for the rate limits on login, sign-up and verify. They use the REAL counter
(on the in-memory test database), with small limits so the tests stay short."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import breakmyapi.api.main as main
from breakmyapi.limits import wait_if_over

PASSWORD = "long enough password"


@pytest.fixture
def settings(monkeypatch):
    """Change a setting for one test only: settings("login_attempts_per_email", 3)."""
    return lambda name, value: monkeypatch.setattr(main.get_settings(), name, value)


def login(email, password=PASSWORD):
    return TestClient(main.app).post("/auth/login", json={"email": email, "password": password})


# ---- the counter itself ----


def test_fixed_window_counter(db):
    ten_past = datetime(2026, 10, 25, 10, 5, 0, tzinfo=UTC)  # inside the 10:00-10:15 window
    with db() as session:
        for _ in range(3):
            assert wait_if_over(session, "k", 3, 900, now=ten_past) is None  # 3 allowed
        assert wait_if_over(session, "k", 3, 900, now=ten_past) == 600  # 4th: wait until 10:15

        next_window = datetime(2026, 10, 25, 10, 15, 0, tzinfo=UTC)
        assert wait_if_over(session, "k", 3, 900, now=next_window) is None  # new window, fresh start
        assert wait_if_over(session, "other", 3, 900, now=ten_past) is None  # other keys are separate


# ---- login ----


def test_too_many_wrong_passwords_blocks_that_email(priya, settings):
    settings("login_attempts_per_email", 3)
    for _ in range(3):
        assert login("priya@example.com", "wrong password!!").status_code == 401

    blocked = login("priya@example.com", PASSWORD)  # even the RIGHT password is refused now
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0

    assert login("rahul@example.com", "wrong password!!").status_code == 401  # other emails unaffected


def test_blocked_unknown_and_known_emails_look_the_same(priya, settings):
    settings("login_attempts_per_email", 1)
    for email in ["priya@example.com", "nobody@example.com"]:
        login(email, "wrong password!!")
    known, unknown = login("priya@example.com"), login("nobody@example.com")
    assert known.status_code == unknown.status_code == 429
    assert known.json() == unknown.json()  # the limit gives no hint about which accounts exist


def test_email_case_does_not_get_around_the_limit(priya, settings):
    settings("login_attempts_per_email", 2)
    login("priya@example.com", "wrong password!!")
    login("PRIYA@example.com", "wrong password!!")
    assert login(" Priya@Example.com ").status_code == 429


def test_many_emails_from_one_address_are_blocked(db, settings):
    settings("login_attempts_per_ip", 3)
    for i in range(3):
        assert login(f"user{i}@example.com").status_code == 401
    assert login("user99@example.com").status_code == 429


def test_a_blocked_guess_never_checks_the_password(priya, settings, monkeypatch):
    settings("login_attempts_per_email", 1)
    login("priya@example.com", "wrong password!!")

    def must_not_run(*args):
        raise AssertionError("the password was checked although the limit was reached")

    monkeypatch.setattr(main, "log_in", must_not_run)
    assert login("priya@example.com").status_code == 429


# ---- sign-up ----


def test_too_many_signups_from_one_address(db, settings):
    settings("signups_per_ip_per_hour", 2)
    client = TestClient(main.app)
    statuses = [
        client.post("/auth/signup", json={"email": f"new{i}@example.com", "password": PASSWORD}).status_code
        for i in range(3)
    ]
    assert statuses == [201, 201, 429]


# ---- verify ----


def test_too_many_verify_checks(priya, settings, monkeypatch):
    settings("verifies_per_user_per_hour", 2)
    fetches = []
    monkeypatch.setattr(main, "fetch_proof", lambda url: fetches.append(url))  # records, finds nothing

    claim = priya.post("/targets", json={"target_url": "https://api.example.com"}).json()
    statuses = [priya.post(f"/targets/{claim['id']}/verify").status_code for _ in range(3)]

    assert statuses == [400, 400, 429]
    assert len(fetches) == 2  # the blocked check sent no request at all
