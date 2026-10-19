import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from breakmyapi.config import get_settings
from breakmyapi.db import get_session, init_db
from breakmyapi.models import Scan
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    if not parse_endpoints(spec):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Spec defines no endpoints")

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
