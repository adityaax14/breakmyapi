import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import APIError
from pydantic import BaseModel, ConfigDict, Field
from redis import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from breakmyapi.checks import CHECKS
from breakmyapi.config import get_settings
from breakmyapi.db import SessionLocal, get_session, init_db
from breakmyapi.jobs import enqueue_scan
from breakmyapi.limits import limit_asks
from breakmyapi.llm.client import LLMConfigError
from breakmyapi.models import Scan, ScanEvent, TargetClaim
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
    allow_headers=["Content-Type"],
)


class ScanCreate(BaseModel):
    target_url: str
    spec: str


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_url: str
    status: str


@app.post("/scans", response_model=ScanOut, status_code=status.HTTP_202_ACCEPTED)
def create_scan(body: ScanCreate, session: Session = Depends(get_session)):
    # Safety first: refuse targets we may not scan, before saving or queueing anything.
    try:
        check_target(body.target_url, session)
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

    scan = Scan(target_url=body.target_url, spec=spec)
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


@app.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: uuid.UUID, session: Session = Depends(get_session)):
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
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
    session: Session = Depends(get_session),
):
    """One page of scans, newest first."""
    total = session.scalar(select(func.count()).select_from(Scan))
    scans = session.scalars(
        select(Scan)
        .options(load_only(Scan.id, Scan.target_url, Scan.status, Scan.created_at))  # skip the big spec column
        .order_by(Scan.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ScanPage(items=[ScanSummary.model_validate(s) for s in scans], total=total)


FINISHED = {"completed", "failed", "cancelled"}


@app.post("/scans/{scan_id}/cancel", response_model=ScanOut)
def cancel_scan(scan_id: uuid.UUID, session: Session = Depends(get_session)):
    """Stop a scan that is waiting or running. The worker notices before its next step."""
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")

    if change_status(session, scan_id, {"queued", "running"}, "cancelled"):
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
def stream_scan(scan_id: uuid.UUID, session: Session = Depends(get_session)):
    """Server-Sent Events: keep the connection open and push each new diary line as it is written."""
    if session.get(Scan, scan_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")

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
def create_claim(body: ClaimCreate, session: Session = Depends(get_session)):
    """Step 1: "I own this API." We answer with a secret to publish on it."""
    try:
        origin = origin_of(body.target_url)
    except TargetError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    claim = TargetClaim(origin=origin, token=new_token())
    session.add(claim)
    session.commit()
    return claim_out(claim)


@app.post("/targets/{claim_id}/verify", response_model=ClaimOut)
def verify_claim(claim_id: uuid.UUID, session: Session = Depends(get_session)):
    """Step 2: "I published it, check now." We fetch the file and compare it with the token."""
    claim = session.get(TargetClaim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if claim.verified_at is not None:
        return claim_out(claim)  # already verified: nothing to fetch again

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
