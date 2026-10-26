import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import APIError
from pydantic import BaseModel, ConfigDict, Field
from redis import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from breakmyapi.auth import (
    current_token,
    current_user,
    end_session,
    hash_password,
    log_in,
    normalize_email,
    start_session,
)
from breakmyapi.checks import CHECKS
from breakmyapi.config import get_settings
from breakmyapi.db import SessionLocal, get_session, init_db
from breakmyapi.jobs import enqueue_scan
from breakmyapi.limits import client_ip, limit_asks, too_many, wait_if_over
from breakmyapi.llm.client import LLMConfigError
from breakmyapi.models import Scan, ScanEvent, TargetClaim, User
from breakmyapi.rag.answer import answer, body_of
from breakmyapi.rag.search import search
from breakmyapi.scan_runner import change_status
from breakmyapi.spec.parser import SpecError, load_spec, parse_endpoints
from breakmyapi.netguard import BlockedAddress
from breakmyapi.ownership import fetch_proof, new_token, proof_matches, proof_url
from breakmyapi.targets import TargetError, TargetNotAllowed, check_target, origin_of


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BreakMyAPI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],  # Authorization carries the login token
)


class ScanCreate(BaseModel):
    target_url: str
    spec: str
    # Which framework the fix advice should be written for (fixed choices, so nothing odd reaches the prompt).
    framework: Literal["generic", "fastapi", "django", "express", "spring"] = "generic"
    # Optional: a bearer token for a THROWAWAY test account on your target. Only used by checks
    # that need to be logged in. Log in as that account yourself and paste its token here; we
    # never attempt to log in on your behalf or guess credentials.
    test_token: str | None = Field(default=None, max_length=2000)


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_url: str
    status: str


def own_scan(session: Session, scan_id: uuid.UUID, user: User) -> Scan:
    """The scan, but only if it belongs to this user.

    Someone else's scan gets the SAME 404 as a scan that doesn't exist, so nobody can even
    learn that it exists. Skipping this check is exactly the bug BreakMyAPI looks for in other
    people's APIs (BOLA: Broken Object Level Authorization), so we must not have it ourselves.
    """
    scan = session.get(Scan, scan_id)
    if scan is None or scan.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


@app.post("/scans", response_model=ScanOut, status_code=status.HTTP_202_ACCEPTED)
def create_scan(
    body: ScanCreate, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    # Safety first: refuse targets we may not scan, before saving or queueing anything.
    try:
        check_target(body.target_url, session, user.id)
    except TargetNotAllowed as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except TargetError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    try:
        spec = load_spec(body.spec)
    except SpecError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    if not parse_endpoints(spec):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Spec defines no endpoints")

    scan = Scan(target_url=body.target_url, spec=spec, user_id=user.id, framework=body.framework,
                test_token=body.test_token)
    session.add(scan)
    session.commit()  # save first, so the worker can always find the scan it is given

    try:
        enqueue_scan(scan.id)  # hand the job to the worker (through Redis) instead of running it here
    except RedisError as e:
        # The queue is down: don't leave a scan "queued" forever that no worker will ever see.
        scan.status = "failed"
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable. Try again shortly.") from e
    return scan


class ScanDetail(ScanOut):
    """One scan with everything the progress page needs, including a pending approval question."""

    approval_request: dict | None  # {"tests": [...]} while status is "waiting_approval"
    approval: str | None           # the user's answer, once given
    framework: str                 # fixes in the report are written for this framework
    report: dict | None            # {"summary": ..., "sections": [...]} once the scan has completed


@app.get("/scans/{scan_id}", response_model=ScanDetail)
def get_scan(scan_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return own_scan(session, scan_id, user)


class ApprovalIn(BaseModel):
    decision: Literal["approve", "reject"]  # anything else is refused with 422 before our code runs


@app.post("/scans/{scan_id}/approval", response_model=ScanDetail)
def answer_approval(
    scan_id: uuid.UUID, body: ApprovalIn, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    """The user's answer to the agent's question. Saves it, and puts the scan back in the queue to resume."""
    scan = own_scan(session, scan_id, user)

    # One statement checks AND changes (as in Lesson 34): only a scan that is waiting can be answered,
    # so answering twice, or answering a cancelled scan, can never resume it twice.
    result = session.execute(
        update(Scan)
        .where(Scan.id == scan_id, Scan.status == "waiting_approval")
        .values(status="queued", approval=body.decision)
    )
    if result.rowcount == 0:
        session.rollback()
        session.refresh(scan)
        raise HTTPException(status.HTTP_409_CONFLICT, f"This scan is not waiting for approval (it is {scan.status})")
    session.add(ScanEvent(scan_id=scan_id, message=f"you answered: {body.decision}"))
    session.commit()

    try:
        enqueue_scan(scan_id)  # any worker will pick it up and resume the agent with the answer
    except RedisError as e:
        # The queue is down: put it back to "waiting" so the user can simply answer again later.
        session.execute(
            update(Scan).where(Scan.id == scan_id).values(status="waiting_approval", approval=None)
        )
        session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable. Try again shortly.") from e

    session.refresh(scan)
    return scan


MAX_PAGE_SIZE = 50  # nobody can ask for more than this many scans at once (check 10, applied to ourselves)


class ScanSummary(ScanOut):
    created_at: datetime


class ScanPage(BaseModel):
    items: list[ScanSummary]
    total: int  # how many scans exist in all, so the page can say "showing 1-20 of 57"


@app.get("/scans", response_model=ScanPage)
def list_scans(
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """One page of YOUR scans, newest first."""
    total = session.scalar(select(func.count()).select_from(Scan).where(Scan.user_id == user.id))
    scans = session.scalars(
        select(Scan)
        .where(Scan.user_id == user.id)
        .options(load_only(Scan.id, Scan.target_url, Scan.status, Scan.created_at))  # skip the big spec column
        .order_by(Scan.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ScanPage(items=[ScanSummary.model_validate(s) for s in scans], total=total)


FINISHED = {"completed", "failed", "cancelled"}


@app.post("/scans/{scan_id}/cancel", response_model=ScanOut)
def cancel_scan(scan_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Stop a scan that is waiting or running. The worker notices before its next step."""
    scan = own_scan(session, scan_id, user)

    if change_status(session, scan_id, {"queued", "running", "waiting_approval"}, "cancelled"):
        session.add(ScanEvent(scan_id=scan_id, message="scan cancelled"))
        session.commit()
        session.refresh(scan)
        return scan

    session.rollback()
    session.refresh(scan)
    if scan.status == "cancelled":
        return scan  # pressing Cancel twice is fine: same result, no error
    raise HTTPException(status.HTTP_409_CONFLICT, f"The scan is already {scan.status}")


@app.get("/scans/{scan_id}/stream")
def stream_scan(scan_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Server-Sent Events: keep the connection open and push each new diary line as it is written."""
    own_scan(session, scan_id, user)  # checked once, before streaming starts

    def events():
        last_id = 0  # the newest diary line already sent; a new connection starts from the beginning
        while True:
            with SessionLocal() as db:
                scan = db.get(Scan, scan_id)
                new_lines = db.scalars(
                    select(ScanEvent)
                    .where(ScanEvent.scan_id == scan_id, ScanEvent.id > last_id)
                    .order_by(ScanEvent.id)
                ).all()
                for line in new_lines:
                    last_id = line.id
                    yield f"data: {json.dumps({'message': line.message, 'status': scan.status})}\n\n"
                if scan.status in FINISHED:
                    yield f"event: done\ndata: {json.dumps({'status': scan.status})}\n\n"
                    return
            time.sleep(0.5)  # look for new lines twice a second

    return StreamingResponse(events(), media_type="text/event-stream")


# ---- accounts: sign up, log in, log out ----


class Credentials(BaseModel):
    # something@something.something (spaces around it are allowed: normalize_email trims them)
    email: str = Field(max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")
    # At least 10 characters (length beats complexity rules). At most 128, so nobody can make us
    # hash a 10 MB "password" (Argon2 is deliberately slow).
    password: str = Field(min_length=10, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str


class LoginOut(BaseModel):
    token: str  # send it back on every request as:  Authorization: Bearer <token>
    user: UserOut


@app.post("/auth/signup", response_model=LoginOut, status_code=status.HTTP_201_CREATED)
def sign_up(body: Credentials, request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    wait = wait_if_over(session, f"signup-ip:{client_ip(request)}", settings.signups_per_ip_per_hour, 3600)
    if wait:
        raise too_many(wait, "Too many new accounts from your network. Try again later.")

    user = User(email=normalize_email(body.email), password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError as e:
        # The database's UNIQUE rule on email refused it. (Checking with a SELECT first would
        # not be enough: two sign-ups at the same moment could both pass the check.)
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from e
    return LoginOut(token=start_session(session, user), user=UserOut.model_validate(user))


@app.post("/auth/login", response_model=LoginOut)
def log_in_endpoint(body: Credentials, request: Request, session: Session = Depends(get_session)):
    # Count the attempt BEFORE checking the password, so a blocked guess costs us nothing.
    # Two counters: per email (someone guessing one account's password from many places) and
    # per IP (one place guessing many accounts). Both always count; the longer wait wins.
    settings = get_settings()
    window = settings.login_window_seconds
    waits = [
        wait_if_over(session, f"login-email:{normalize_email(body.email)}", settings.login_attempts_per_email, window),
        wait_if_over(session, f"login-ip:{client_ip(request)}", settings.login_attempts_per_ip, window),
    ]
    wait = max((w for w in waits if w), default=None)
    if wait:
        # The same answer whether the email exists or not (no hints about which accounts exist).
        raise too_many(wait, "Too many login attempts. Wait a few minutes and try again.")

    user = log_in(session, body.email, body.password)
    if user is None:
        # The same answer for "no such email" and "wrong password", so nobody can use this
        # endpoint to find out which emails have accounts.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    return LoginOut(token=start_session(session, user), user=UserOut.model_validate(user))


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def log_out(
    token: str = Depends(current_token),
    user: User = Depends(current_user),  # only a valid session can be logged out
    session: Session = Depends(get_session),
):
    end_session(session, token)


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    """Who am I? The frontend calls this on start-up to check that its saved token still works."""
    return user


# ---- ownership verification: prove you own an API before scanning it ----


class ClaimCreate(BaseModel):
    target_url: str


class ClaimOut(BaseModel):
    id: uuid.UUID
    origin: str
    verified: bool
    proof_url: str  # where the owner must publish the token
    token: str      # what the file must contain, exactly


def claim_out(claim: TargetClaim) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        origin=claim.origin,
        verified=claim.verified_at is not None,
        proof_url=proof_url(claim.origin),
        token=claim.token,
    )


@app.post("/targets", response_model=ClaimOut, status_code=status.HTTP_201_CREATED)
def create_claim(body: ClaimCreate, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Step 1: "I own this API." We answer with a secret to publish on it."""
    try:
        origin = origin_of(body.target_url)
    except TargetError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    claim = TargetClaim(origin=origin, token=new_token(), user_id=user.id)
    session.add(claim)
    session.commit()
    return claim_out(claim)


@app.post("/targets/{claim_id}/verify", response_model=ClaimOut)
def verify_claim(claim_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Step 2: "I published it, check now." We fetch the file and compare it with the token."""
    claim = session.get(TargetClaim, claim_id)
    if claim is None or claim.user_id != user.id:  # someone else's claim: same 404, as with scans
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if claim.verified_at is not None:
        return claim_out(claim)  # already verified: nothing to fetch again

    # Each check makes OUR server send a request somewhere, so nobody may use us to send many.
    wait = wait_if_over(session, f"verify-user:{user.id}", get_settings().verifies_per_user_per_hour, 3600)
    if wait:
        raise too_many(wait, "Too many verification checks. Try again later.")

    url = proof_url(claim.origin)
    try:
        found = fetch_proof(url)
    except BlockedAddress as e:
        # The name points inside a private network: we refuse to send the request at all.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Refused: {e}") from e
    if not proof_matches(found, claim.token):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Could not find the token at {url}. Publish it there exactly (as plain text), then try again.",
        )
    claim.verified_at = datetime.now(UTC)
    session.commit()
    return claim_out(claim)


# ---- the OWASP library (RAG search) ----


class CheckOut(BaseModel):
    id: str
    name: str


class LibraryHit(BaseModel):
    chunk_id: str
    heading: str
    url: str
    score: float
    text: str


@app.get("/library/checks", response_model=list[CheckOut])
def library_checks():
    """The check types, so the frontend can offer them as a filter."""
    return [CheckOut(id=c.id, name=c.name) for c in CHECKS.values()]


@app.get("/library/search", response_model=list[LibraryHit])
def library_search(
    q: str = Query(min_length=3, max_length=500),
    check: str | None = None,
    k: int = Query(default=5, ge=1, le=10),
):
    """Search the OWASP library by meaning, optionally only within one check's documents."""
    if check is not None and check not in CHECKS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown check: {check}")
    return [
        LibraryHit(
            chunk_id=hit.chunk_id,
            heading=hit.heading,
            url=hit.url,
            score=hit.score,
            text=body_of(hit),  # the stored text starts with the heading; drop it
        )
        for hit in search(q, k=k, check=check)
    ]


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    check: str | None = None


class AskOut(BaseModel):
    answer: str
    sources: list[LibraryHit]  # numbered [1], [2], ... in this order
    cited: list[int]           # which of those numbers the answer cites
    tokens: int


@app.post("/library/ask", response_model=AskOut, dependencies=[Depends(limit_asks)])
def library_ask(body: AskIn):
    """RAG: find the best sections, then let the LLM answer from them, with citations."""
    if body.check is not None and body.check not in CHECKS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown check: {body.check}")
    try:
        result = answer(body.question, check=body.check)
    except (APIError, LLMConfigError) as e:
        # The model service is down, rate-limited, or not configured: that is not the user's fault,
        # and not a bug in our code either, so answer 503 "service unavailable".
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"The language model is unavailable: {e}") from e

    return AskOut(
        answer=result.text,
        sources=[
            LibraryHit(chunk_id=h.chunk_id, heading=h.heading, url=h.url, score=h.score, text=body_of(h))
            for h in result.sources
        ],
        cited=result.cited,
        tokens=result.tokens,
    )
