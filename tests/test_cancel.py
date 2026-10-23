"""Tests for cancelling a scan: through the API, and the worker noticing it.

They use the `db` fixture from conftest.py: a throwaway in-memory database.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

import breakmyapi.api.main as main
import breakmyapi.scan_runner as scan_runner
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.scan_runner import run_scan

SPEC = {"paths": {"/a": {"get": {}}, "/b": {"get": {}}, "/c": {"get": {}}}}  # 3 endpoints = 3 steps


client = TestClient(main.app)


def add_scan(TestSession, status="queued"):
    with TestSession() as session:
        scan = Scan(target_url="http://localhost:8001", spec=SPEC, status=status)
        session.add(scan)
        session.commit()
        return scan.id


def status_of(TestSession, scan_id):
    with TestSession() as session:
        return session.get(Scan, scan_id).status


def diary(TestSession, scan_id):
    with TestSession() as session:
        return session.scalars(select(ScanEvent.message).where(ScanEvent.scan_id == scan_id).order_by(ScanEvent.id)).all()


def test_cancelling_a_queued_scan_means_the_worker_never_starts_it(db):
    scan_id = add_scan(db)

    response = client.post(f"/scans/{scan_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    run_scan(scan_id)  # the worker takes it from the queue later...
    assert status_of(db, scan_id) == "cancelled"  # ...and leaves it alone
    assert diary(db, scan_id) == ["scan cancelled"]


def test_cancelling_a_running_scan_stops_it_before_the_next_step(db, monkeypatch):
    scan_id = add_scan(db)

    # Press Cancel while the worker is busy with its first step.
    def press_cancel_during_step(seconds):
        if "looked at GET /a" not in diary(db, scan_id):
            client.post(f"/scans/{scan_id}/cancel")

    monkeypatch.setattr(scan_runner.time, "sleep", press_cancel_during_step)
    run_scan(scan_id)

    lines = diary(db, scan_id)
    assert status_of(db, scan_id) == "cancelled"  # NOT overwritten with "completed"
    assert "scan cancelled" in lines
    assert "looked at GET /b" not in lines  # it stopped instead of doing the remaining steps
    assert "scan completed" not in lines


def test_cancelling_twice_is_fine(db):
    scan_id = add_scan(db)
    assert client.post(f"/scans/{scan_id}/cancel").status_code == 200
    assert client.post(f"/scans/{scan_id}/cancel").status_code == 200
    assert diary(db, scan_id) == ["scan cancelled"]  # only one diary line


def test_a_finished_scan_cannot_be_cancelled(db):
    scan_id = add_scan(db, status="completed")
    response = client.post(f"/scans/{scan_id}/cancel")
    assert response.status_code == 409
    assert status_of(db, scan_id) == "completed"


def test_cancelling_an_unknown_scan_is_404(db):
    assert client.post("/scans/00000000-0000-0000-0000-000000000000/cancel").status_code == 404


def test_the_worker_refuses_a_target_that_is_not_allowed(db):
    # As if the scan got into the queue some other way, or the allowlist changed after queueing.
    with db() as session:
        scan = Scan(target_url="http://example.com", spec=SPEC)
        session.add(scan)
        session.commit()

    run_scan(scan.id)
    assert status_of(db, scan.id) == "failed"
    lines = diary(db, scan.id)
    assert lines[-1].startswith("refused:")
    assert not any(line.startswith("looked at") for line in lines)  # nothing was sent


def test_a_scan_nobody_cancels_still_completes(db):
    scan_id = add_scan(db)
    run_scan(scan_id)
    assert status_of(db, scan_id) == "completed"
    assert diary(db, scan_id)[-1] == "scan completed"
