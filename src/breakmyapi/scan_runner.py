import time
import traceback
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from breakmyapi.db import SessionLocal
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.spec.parser import parse_endpoints
from breakmyapi.targets import TargetError, check_target


def log(session: Session, scan: Scan, message: str) -> None:
    """Write one line in the scan's diary and save it at once, so the live stream can see it."""
    session.add(ScanEvent(scan_id=scan.id, message=message))
    session.commit()  # also saves any change to the scan itself, such as its status


def change_status(session: Session, scan_id: uuid.UUID, only_if: set[str], new_status: str) -> bool:
    """Change a scan's status, but ONLY if it is currently one of `only_if`. Returns True if it changed.

    The check and the change are ONE SQL statement:
        UPDATE scans SET status = 'cancelled' WHERE id = ... AND status IN ('queued', 'running')
    so two programs (the API and the worker) can never both "win": the database applies them
    one after the other, and the second one finds the status already changed and matches nothing.
    """
    result = session.execute(
        update(Scan).where(Scan.id == scan_id, Scan.status.in_(only_if)).values(status=new_status)
    )
    return result.rowcount == 1


class Cancelled(Exception):
    """The user pressed Cancel while this scan was running."""


def stop_if_cancelled(session: Session, scan: Scan) -> None:
    """Read the scan's status again from the database. If the user cancelled it, stop here."""
    session.refresh(scan)  # our copy is old: the API may have changed the status since we loaded it
    if scan.status == "cancelled":
        raise Cancelled


def prepare_retry(scan_id: uuid.UUID) -> None:
    """A worker crashed in the middle of this scan: set it back to "queued" so it can run again."""
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        if scan is not None and change_status(session, scan_id, {"running"}, "queued"):
            log(session, scan, "the worker stopped during this scan; it will run again")


def run_scan(scan_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        # Only start it if it is still waiting. A scan cancelled while in the queue stops here.
        if scan is None or not change_status(session, scan_id, {"queued"}, "running"):
            session.commit()
            return
        log(session, scan, "scan started")

        try:
            # Check again here, not only in the API: the allowlist may have changed since the scan
            # was queued, and a scan could reach the queue some other way. (Defense in depth.)
            check_target(scan.target_url, session)

            endpoints = parse_endpoints(scan.spec)
            log(session, scan, f"read the spec: {len(endpoints)} endpoints")

            # Placeholder: the real agent will run here. For now, pretend to look at each endpoint.
            for endpoint in endpoints:
                stop_if_cancelled(session, scan)  # look before every step, so Cancel takes effect quickly
                time.sleep(1)
                log(session, scan, f"looked at {endpoint.method} {endpoint.path}")

            # "completed" only if nobody cancelled it during the last step.
            if change_status(session, scan_id, {"running"}, "completed"):
                log(session, scan, "scan completed")
            session.commit()
        except Cancelled:
            print(f"scan {scan_id} was cancelled; stopped", flush=True)
        except TargetError as e:
            # Not a crash, a refusal: say why in the diary, and send nothing to the target.
            if change_status(session, scan_id, {"running"}, "failed"):
                log(session, scan, f"refused: {e}")
            session.commit()
        except Exception:
            traceback.print_exc()
            session.rollback()
            if change_status(session, scan_id, {"running"}, "failed"):
                log(session, scan, "scan failed")
            session.commit()
