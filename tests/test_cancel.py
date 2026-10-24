"""Tests for cancelling a scan: through the API, and the worker noticing it.

They use the `db` fixture from conftest.py: a throwaway in-memory database.
"""

from sqlalchemy import select

from breakmyapi.models import Scan, ScanEvent
from breakmyapi.rag import search as library
from breakmyapi.scan_runner import run_scan

SPEC = {"paths": {"/a": {"get": {}}, "/b": {"get": {}}, "/c": {"get": {}}}}


def add_scan(TestSession, user_id, status="queued"):
    with TestSession() as session:
        scan = Scan(
            target_url="http://localhost:8001",
            spec=SPEC,
            status=status,
            user_id=user_id,
        )
        session.add(scan)
        session.commit()
        return scan.id


def status_of(TestSession, scan_id):
    with TestSession() as session:
        return session.get(Scan, scan_id).status


def diary(TestSession, scan_id):
    with TestSession() as session:
        return session.scalars(
            select(ScanEvent.message)
            .where(ScanEvent.scan_id == scan_id)
            .order_by(ScanEvent.id)
        ).all()


def test_cancelling_a_queued_scan_means_the_worker_never_starts_it(db, priya):
    scan_id = add_scan(db, priya.user_id)

    response = priya.post(f"/scans/{scan_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    run_scan(scan_id)  # the worker takes it from the queue later...
    assert status_of(db, scan_id) == "cancelled"  # ...and leaves it alone
    assert diary(db, scan_id) == ["scan cancelled"]


def test_cancelling_a_running_scan_stops_it_before_the_next_step(
    db, priya, monkeypatch
):
    scan_id = add_scan(db, priya.user_id)

    # Press Cancel while the agent is busy with its `retrieve` step (the library search).
    real_search = library.search

    def search_and_press_cancel(*args, **kwargs):
        priya.post(f"/scans/{scan_id}/cancel")
        return real_search(*args, **kwargs)

    monkeypatch.setattr(library, "search", search_and_press_cancel)
    run_scan(scan_id)

    lines = diary(db, scan_id)
    assert status_of(db, scan_id) == "cancelled"  # NOT overwritten with "completed"
    assert "scan cancelled" in lines
    assert not any(
        line.startswith("planned") for line in lines
    )  # stopped before the next node
    assert "scan completed" not in lines


def test_cancelling_twice_is_fine(db, priya):
    scan_id = add_scan(db, priya.user_id)
    assert priya.post(f"/scans/{scan_id}/cancel").status_code == 200
    assert priya.post(f"/scans/{scan_id}/cancel").status_code == 200
    assert diary(db, scan_id) == ["scan cancelled"]  # only one diary line


def test_a_finished_scan_cannot_be_cancelled(db, priya):
    scan_id = add_scan(db, priya.user_id, status="completed")
    response = priya.post(f"/scans/{scan_id}/cancel")
    assert response.status_code == 409
    assert status_of(db, scan_id) == "completed"


def test_cancelling_an_unknown_scan_is_404(priya):
    assert (
        priya.post("/scans/00000000-0000-0000-0000-000000000000/cancel").status_code
        == 404
    )


def test_the_worker_refuses_a_target_that_is_not_allowed(db, priya):
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


def test_a_scan_nobody_cancels_still_completes(db, priya):
    scan_id = add_scan(db, priya.user_id)
    run_scan(scan_id)
    assert status_of(db, scan_id) == "completed"
    assert diary(db, scan_id)[-1] == "scan completed"
