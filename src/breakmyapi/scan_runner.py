import time
import traceback
import uuid

from sqlalchemy.orm import Session

from breakmyapi.db import SessionLocal
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.spec.parser import parse_endpoints


def log(session: Session, scan: Scan, message: str) -> None:
    """Write one line in the scan's diary and save it at once, so the live stream can see it."""
    session.add(ScanEvent(scan_id=scan.id, message=message))
    session.commit()  # also saves any change to the scan itself, such as its status


def run_scan(scan_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        if scan is None or scan.status != "queued":
            return

        scan.status = "running"
        log(session, scan, "scan started")

        try:
            endpoints = parse_endpoints(scan.spec)
            log(session, scan, f"read the spec: {len(endpoints)} endpoints")

            # Placeholder: the real agent will run here. For now, pretend to look at each endpoint.
            for endpoint in endpoints:
                time.sleep(1)
                log(session, scan, f"looked at {endpoint.method} {endpoint.path}")

            scan.status = "completed"
            log(session, scan, "scan completed")
        except Exception:
            traceback.print_exc()
            session.rollback()
            scan.status = "failed"
            log(session, scan, "scan failed")
