import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import APIError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from breakmyapi.checks import CHECKS
from breakmyapi.config import get_settings
from breakmyapi.db import SessionLocal, get_session, init_db
from breakmyapi.llm.client import LLMConfigError
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.rag.answer import answer, body_of
from breakmyapi.rag.search import search
from breakmyapi.scan_runner import run_scan
from breakmyapi.spec.parser import SpecError, load_spec, parse_endpoints


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
def create_scan(body: ScanCreate, background: BackgroundTasks, session: Session = Depends(get_session)):
    try:
        spec = load_spec(body.spec)
    except SpecError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    if not parse_endpoints(spec):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Spec defines no endpoints")

    scan = Scan(target_url=body.target_url, spec=spec)
    session.add(scan)
    session.commit()
    background.add_task(run_scan, scan.id)
    return scan


@app.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: uuid.UUID, session: Session = Depends(get_session)):
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


FINISHED = {"completed", "failed", "cancelled"}


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


@app.post("/library/ask", response_model=AskOut)
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
