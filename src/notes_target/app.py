"""A small notes API that we scan on purpose.

With no flags it is the safe version. VULN_FLAGS switches known bugs on, one by one,
so we always know the ground truth when we measure the scanner.

Never expose this app outside localhost.
Run safe:     uv run uvicorn notes_target.app:app --port 8001
Run buggy:    $env:VULN_FLAGS="bola,missing_auth"; uv run uvicorn notes_target.app:app --port 8001
"""

import hashlib
import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

app = FastAPI(title="Notes API", version="1.0.0")
bearer = HTTPBearer(auto_error=False)

# Each name switches ONE known bug on. With no flags, the app is the safe version.
ALL_FLAGS = {"bola", "missing_auth", "mass_assignment", "excessive_data"}
_raw_flags = os.getenv("VULN_FLAGS", "")
FLAGS = ALL_FLAGS if _raw_flags.strip() == "all" else {f.strip() for f in _raw_flags.split(",") if f.strip()}
if FLAGS - ALL_FLAGS:
    raise ValueError(f"Unknown VULN_FLAGS: {sorted(FLAGS - ALL_FLAGS)}")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# The "database": plain dictionaries in memory. Everything resets when the server restarts.
USERS = {
    1: {"id": 1, "username": "alice", "display_name": "Alice", "email": "alice@example.com",
        "role": "user", "password_hash": hash_password("alice-pass")},
    2: {"id": 2, "username": "bob", "display_name": "Bob", "email": "bob@example.com",
        "role": "user", "password_hash": hash_password("bob-pass")},
}
NOTES = {
    1: {"id": 1, "title": "Alice's plan", "body": "private", "owner_id": 1},
    2: {"id": 2, "title": "Alice's diary", "body": "private", "owner_id": 1},
    3: {"id": 3, "title": "Bob's list", "body": "private", "owner_id": 2},
}
TOKENS: dict[str, int] = {}  # token -> user id


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class NoteIn(BaseModel):
    title: str
    body: str = ""


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None


class NoteOut(BaseModel):
    id: int
    title: str
    body: str
    owner_id: int


class UserUpdate(BaseModel):
    display_name: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str


def user_from_token(creds: HTTPAuthorizationCredentials | None) -> dict | None:
    """Return the logged-in user for this token, or None if there isn't one."""
    user_id = TOKENS.get(creds.credentials) if creds else None
    return USERS[user_id] if user_id is not None else None


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    user = user_from_token(creds)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def get_own_note(note_id: int, user: dict) -> dict:
    note = NOTES.get(note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    # The ownership check. With the "bola" flag on, this check is skipped.
    # A note that belongs to someone else gets the same 404 as one that does not
    # exist, so callers cannot discover which note ids exist.
    if "bola" not in FLAGS and note["owner_id"] != user["id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return note


@app.post("/login", response_model=TokenOut)
def login(body: LoginIn):
    for user in USERS.values():
        if user["username"] == body.username and user["password_hash"] == hash_password(body.password):
            token = secrets.token_urlsafe(24)
            TOKENS[token] = user["id"]
            return TokenOut(access_token=token)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


@app.get("/users/me", response_model=UserOut)
def get_me(user: dict = Depends(current_user)):
    if "excessive_data" in FLAGS:
        # The bug: returning a Response object skips response_model,
        # so the raw record leaks, including email and password_hash.
        return JSONResponse(user)
    # Safe: response_model=UserOut keeps only id, username, display_name and role.
    return user


@app.patch("/users/me", response_model=UserOut)
async def update_me(body: UserUpdate, request: Request, user: dict = Depends(current_user)):
    if "mass_assignment" in FLAGS:
        # The bug: copy every field the client sent, including ones it must never control (role).
        for key, value in (await request.json()).items():
            if key in user and key != "id":
                user[key] = value
    else:
        # Safe: UserUpdate only knows display_name, so anything else the client sends is ignored.
        user.update(body.model_dump(exclude_unset=True))
    return user


@app.get("/notes", response_model=list[NoteOut])
def list_notes(creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
    user = user_from_token(creds)
    if user is None:
        if "missing_auth" in FLAGS:
            # The bug: no valid token, and the server answers anyway, with everyone's notes.
            return list(NOTES.values())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return [n for n in NOTES.values() if n["owner_id"] == user["id"]]


@app.post("/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(body: NoteIn, user: dict = Depends(current_user)):
    note = {"id": max(NOTES) + 1, "title": body.title, "body": body.body, "owner_id": user["id"]}
    NOTES[note["id"]] = note
    return note


@app.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, user: dict = Depends(current_user)):
    return get_own_note(note_id, user)


@app.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, body: NoteUpdate, user: dict = Depends(current_user)):
    note = get_own_note(note_id, user)
    note.update(body.model_dump(exclude_unset=True))
    return note


@app.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, user: dict = Depends(current_user)):
    get_own_note(note_id, user)
    del NOTES[note_id]
