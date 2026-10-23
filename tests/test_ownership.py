"""Tests for ownership verification.

We never contact a real server here: `fake_server` replaces fetch_proof with a function that
answers from a dictionary {url: file text}, like a pretend internet we control.
"""

import pytest
from fastapi.testclient import TestClient

import breakmyapi.api.main as main
from breakmyapi.ownership import proof_matches
from breakmyapi.targets import TargetNotAllowed, check_target

client = TestClient(main.app)
SITE = "https://api.example.com"
PROOF = "https://api.example.com:443/.well-known/breakmyapi-verify.txt"
SPEC = "paths:\n  /notes:\n    get: {}\n"


@pytest.fixture
def fake_server(monkeypatch):
    files = {}  # url -> text; a url that is not in here behaves like "not found"
    monkeypatch.setattr(main, "fetch_proof", lambda url: files.get(url))
    return files


def start_claim():
    response = client.post("/targets", json={"target_url": SITE + "/v1/users"})
    assert response.status_code == 201
    return response.json()


def test_a_claim_gives_a_secret_and_where_to_put_it(db):
    claim = start_claim()
    assert claim["origin"] == "https://api.example.com:443"  # the path /v1/users doesn't matter
    assert claim["proof_url"] == PROOF
    assert claim["token"].startswith("breakmyapi-")
    assert claim["verified"] is False


def test_every_claim_gets_a_different_secret(db):
    assert start_claim()["token"] != start_claim()["token"]


def test_verify_fails_when_the_file_is_missing(db, fake_server):
    claim = start_claim()
    response = client.post(f"/targets/{claim['id']}/verify")
    assert response.status_code == 400
    assert PROOF in response.json()["detail"]  # tells the user exactly where to put it


def test_verify_fails_when_the_file_has_the_wrong_secret(db, fake_server):
    claim = start_claim()
    fake_server[PROOF] = "breakmyapi-a-different-secret"
    assert client.post(f"/targets/{claim['id']}/verify").status_code == 400


def test_verify_succeeds_when_the_secret_is_published(db, fake_server):
    claim = start_claim()
    fake_server[PROOF] = claim["token"]
    response = client.post(f"/targets/{claim['id']}/verify")
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_a_verified_site_can_be_scanned_and_an_unverified_one_cannot(db, fake_server):
    # Before: not on the allowlist, not verified -> 403.
    assert client.post("/scans", json={"target_url": SITE, "spec": SPEC}).status_code == 403

    claim = start_claim()
    fake_server[PROOF] = claim["token"]
    client.post(f"/targets/{claim['id']}/verify")

    # After: the API accepts it. (It answers 503 here only because tests have no Redis queue.)
    assert client.post("/scans", json={"target_url": SITE, "spec": SPEC}).status_code != 403
    # ...and the check itself, as the worker runs it, agrees.
    with db() as session:
        check_target(SITE + "/anything", session)


def test_an_unverified_claim_does_not_count(db):
    start_claim()  # claimed, but the secret was never published
    with db() as session, pytest.raises(TargetNotAllowed):
        check_target(SITE, session)


def test_verifying_one_site_does_not_unlock_another(db, fake_server):
    claim = start_claim()
    fake_server[PROOF] = claim["token"]
    client.post(f"/targets/{claim['id']}/verify")
    with db() as session, pytest.raises(TargetNotAllowed):
        check_target("https://evil.example.com", session)


def test_unknown_claim_is_404(db):
    assert client.post("/targets/00000000-0000-0000-0000-000000000000/verify").status_code == 404


def test_broken_url_cannot_be_claimed(db):
    assert client.post("/targets", json={"target_url": "file:///etc/passwd"}).status_code == 422


@pytest.mark.parametrize(
    ("found", "token", "match"),
    [
        ("breakmyapi-abc", "breakmyapi-abc", True),
        ("breakmyapi-abd", "breakmyapi-abc", False),
        ("", "breakmyapi-abc", False),
        (None, "breakmyapi-abc", False),  # file could not be read
        ("breakmyapi-é", "breakmyapi-abc", False),  # non-English characters must not crash it
    ],
)
def test_proof_matches(found, token, match):
    assert proof_matches(found, token) is match
