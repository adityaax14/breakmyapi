"""Tests for ownership verification.

We never contact a real server here: `fake_server` replaces fetch_proof with a function that
answers from a dictionary {url: file text}, like a pretend internet we control.
`priya` and `rahul` are two logged-in test users (see conftest.py).
"""

import pytest

import breakmyapi.api.main as main
from breakmyapi.ownership import proof_matches
from breakmyapi.targets import TargetNotAllowed, check_target

SITE = "https://api.example.com"
PROOF = "https://api.example.com:443/.well-known/breakmyapi-verify.txt"
SPEC = "paths:\n  /notes:\n    get: {}\n"


@pytest.fixture
def fake_server(monkeypatch):
    files = {}  # url -> text; a url that is not in here behaves like "not found"
    monkeypatch.setattr(main, "fetch_proof", lambda url: files.get(url))
    return files


def start_claim(client):
    response = client.post("/targets", json={"target_url": SITE + "/v1/users"})
    assert response.status_code == 201
    return response.json()


def verify(client, fake_server):
    """Claim SITE, publish the token on the pretend server, and verify it."""
    claim = start_claim(client)
    fake_server[PROOF] = claim["token"]
    assert client.post(f"/targets/{claim['id']}/verify").status_code == 200


def test_a_claim_gives_a_secret_and_where_to_put_it(priya):
    claim = start_claim(priya)
    assert claim["origin"] == "https://api.example.com:443"  # the path /v1/users doesn't matter
    assert claim["proof_url"] == PROOF
    assert claim["token"].startswith("breakmyapi-")
    assert claim["verified"] is False


def test_claims_need_a_login(db):
    from fastapi.testclient import TestClient

    assert TestClient(main.app).post("/targets", json={"target_url": SITE}).status_code == 401


def test_every_claim_gets_a_different_secret(priya):
    assert start_claim(priya)["token"] != start_claim(priya)["token"]


def test_verify_fails_when_the_file_is_missing(priya, fake_server):
    claim = start_claim(priya)
    response = priya.post(f"/targets/{claim['id']}/verify")
    assert response.status_code == 400
    assert PROOF in response.json()["detail"]  # tells the user exactly where to put it


def test_verify_fails_when_the_file_has_the_wrong_secret(priya, fake_server):
    claim = start_claim(priya)
    fake_server[PROOF] = "breakmyapi-a-different-secret"
    assert priya.post(f"/targets/{claim['id']}/verify").status_code == 400


def test_verify_succeeds_when_the_secret_is_published(priya, fake_server):
    claim = start_claim(priya)
    fake_server[PROOF] = claim["token"]
    response = priya.post(f"/targets/{claim['id']}/verify")
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_a_verified_site_can_be_scanned_and_an_unverified_one_cannot(db, priya, fake_server):
    # Before: not on the allowlist, not verified -> 403.
    assert priya.post("/scans", json={"target_url": SITE, "spec": SPEC}).status_code == 403

    verify(priya, fake_server)

    # After: the API accepts it. (It answers 503 here only because tests have no Redis queue.)
    assert priya.post("/scans", json={"target_url": SITE, "spec": SPEC}).status_code != 403
    # ...and the check itself, as the worker runs it, agrees.
    with db() as session:
        check_target(SITE + "/anything", session, priya.user_id)


def test_someone_elses_verification_does_not_count_for_you(db, priya, rahul, fake_server):
    verify(priya, fake_server)  # Priya proved she owns the site...

    # ...so Rahul still may not scan it.
    assert rahul.post("/scans", json={"target_url": SITE, "spec": SPEC}).status_code == 403
    with db() as session, pytest.raises(TargetNotAllowed):
        check_target(SITE, session, rahul.user_id)


def test_you_cannot_verify_someone_elses_claim(priya, rahul, fake_server):
    claim = start_claim(priya)
    fake_server[PROOF] = claim["token"]
    assert rahul.post(f"/targets/{claim['id']}/verify").status_code == 404


def test_an_unverified_claim_does_not_count(db, priya):
    start_claim(priya)  # claimed, but the secret was never published
    with db() as session, pytest.raises(TargetNotAllowed):
        check_target(SITE, session, priya.user_id)


def test_verifying_one_site_does_not_unlock_another(db, priya, fake_server):
    verify(priya, fake_server)
    with db() as session, pytest.raises(TargetNotAllowed):
        check_target("https://evil.example.com", session, priya.user_id)


def test_unknown_claim_is_404(priya):
    assert priya.post("/targets/00000000-0000-0000-0000-000000000000/verify").status_code == 404


def test_broken_url_cannot_be_claimed(priya):
    assert priya.post("/targets", json={"target_url": "file:///etc/passwd"}).status_code == 422


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
