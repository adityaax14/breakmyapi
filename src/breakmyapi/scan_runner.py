import time
import traceback
import uuid

from breakmyapi.db import SessionLocal
from breakmyapi.models import Scan
from breakmyapi.spec.parser import parse_endpoints


def run_scan(scan_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        if scan is None or scan.status != "queued":
            return

        scan.status = "running"
        session.commit()

        try:
            endpoints = parse_endpoints(scan.spec)
            print(f"scan {scan_id}: found {len(endpoints)} endpoints")
            time.sleep(5)  # placeholder: the real agent will run here
            scan.status = "completed"
        except Exception:
            traceback.print_exc()
            scan.status = "failed"
        session.commit()
