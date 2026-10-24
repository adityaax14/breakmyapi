"""User accounts: storing passwords safely, logging in, and knowing who is calling.

How a login works here:
  1. Sign up / log in: we check the password, then create a SESSION: a long random token.
  2. We give the token to the browser, and store only a HASH of it in the database.
  3. On every later request the browser sends   Authorization: Bearer <token>
     and `current_user` turns that back into a User (or answers 401).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from breakmyapi.db import get_session
from breakmyapi.models import AuthSession, User

SESSION_DAYS = 7  # after this, log in again

# Argon2: the password hashing method OWASP recommends. It is deliberately SLOW and uses a lot of
# memory, so someone who steals the database cannot try billions of guesses per second.
hasher = PasswordHasher()

# Used when the email does not exist, so a wrong email takes as long as a wrong password (see log_in).
DUMMY_HASH = hasher.hash("not-a-real-password")


def normalize_email(email: str) -> str:
    """" Priya@Example.com " and "priya@example.com" are the same account."""
    return email.strip().lower()


def hash_password(password: str) -> str:
    # The result contains a random "salt", so two users with the same password get different hashes:
    # $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
    return hasher.hash(password)


def password_matches(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    """Session tokens are long random values, so a fast hash (SHA-256) is enough here.
    (Passwords need a slow one because people pick guessable passwords; tokens are not guessable.)"""
    return hashlib.sha256(token.encode()).hexdigest()


def find_user(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == normalize_email(email)))


def log_in(session: Session, email: str, password: str) -> User | None:
    """The user, if the email and password are right; otherwise None. Never says WHICH was wrong."""
    user = find_user(session, email)
    if user is None:
        password_matches(DUMMY_HASH, password)  # same slow work, so timing can't reveal "no such email"
        return None
    return user if password_matches(user.password_hash, password) else None


def start_session(session: Session, user: User) -> str:
    """Create a login session and return its token (the only time the real token exists on our side)."""
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS),
        )
    )
    session.commit()
    return token


def end_session(session: Session, token: str) -> None:
    session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    session.commit()


# Reads "Authorization: Bearer <token>" from the request. auto_error=False: we write our own 401.
bearer = HTTPBearer(auto_error=False)


def current_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Log in first", headers={"WWW-Authenticate": "Bearer"}
        )
    return credentials.credentials


def current_user(token: str = Depends(current_token), session: Session = Depends(get_session)) -> User:
    """FastAPI dependency: the logged-in user, or 401. Add it to any endpoint that needs a login."""
    user = session.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.expires_at > datetime.now(UTC))
    )
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Your session has expired or is not valid. Log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
