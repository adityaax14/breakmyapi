"""Tests for accounts: sign up, log in, log out, and "who is calling?"."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

import breakmyapi.api.main as main
from breakmyapi.auth import hash_password, hash_token, password_matches
from breakmyapi.models import AuthSession, User

client = TestClient(main.app)
PRIYA = {"email": "priya@example.com", "password": "correct horse battery"}


def sign_up(creds=PRIYA):
    return client.post("/auth/signup", json=creds)


def me(token):
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})


# ---- passwords ----


def test_the_password_is_never_stored_only_a_hash(db):
    sign_up()
    with db() as session:
        user = session.scalar(select(User))
    assert PRIYA["password"] not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_same_password_gives_different_hashes():
    # A random "salt" is mixed in, so two users with the same password don't share a hash.
    assert hash_password("same password!") != hash_password("same password!")


def test_password_matches():
    stored = hash_password("correct horse battery")
    assert password_matches(stored, "correct horse battery") is True
    assert password_matches(stored, "Correct horse battery") is False
    assert password_matches("not even a hash", "anything") is False  # a broken hash doesn't crash


# ---- sign up ----


def test_sign_up_logs_you_in(db):
    response = sign_up()
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "priya@example.com"
    assert me(body["token"]).json()["email"] == "priya@example.com"


def test_email_is_case_and_space_insensitive(db):
    sign_up()
    again = sign_up({"email": "  PRIYA@Example.COM ", "password": "another long password"})
    assert again.status_code == 409


def test_short_password_is_rejected(db):
    assert sign_up({"email": "a@b.co", "password": "short"}).status_code == 422


def test_not_an_email_is_rejected(db):
    assert sign_up({"email": "priya", "password": "long enough password"}).status_code == 422


# ---- log in ----


def test_log_in_with_the_right_password(db):
    sign_up()
    response = client.post("/auth/login", json=PRIYA)
    assert response.status_code == 200
    assert me(response.json()["token"]).status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(db):
    sign_up()
    wrong_password = client.post("/auth/login", json={**PRIYA, "password": "wrong password!!"})
    unknown_email = client.post("/auth/login", json={**PRIYA, "email": "nobody@example.com"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()  # nothing reveals which emails exist


def test_each_login_is_a_separate_session(db):
    sign_up()
    phone = client.post("/auth/login", json=PRIYA).json()["token"]
    laptop = client.post("/auth/login", json=PRIYA).json()["token"]
    assert phone != laptop


# ---- sessions ----


def test_no_token_is_401(db):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_made_up_token_is_401(db):
    assert me("i-made-this-up").status_code == 401


def test_only_a_hash_of_the_token_is_stored(db):
    token = sign_up().json()["token"]
    with db() as session:
        stored = session.scalar(select(AuthSession.token_hash))
    assert stored != token
    assert stored == hash_token(token)


def test_expired_session_is_401(db):
    token = sign_up().json()["token"]
    with db() as session:  # pretend 8 days have passed
        session.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        session.commit()
    assert me(token).status_code == 401


def test_log_out_ends_only_that_session(db):
    sign_up()
    phone = client.post("/auth/login", json=PRIYA).json()["token"]
    laptop = client.post("/auth/login", json=PRIYA).json()["token"]

    response = client.post("/auth/logout", headers={"Authorization": f"Bearer {phone}"})
    assert response.status_code == 204
    assert me(phone).status_code == 401   # this device is logged out
    assert me(laptop).status_code == 200  # the other one is not
