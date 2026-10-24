"""Tests for the scan endpoints: login required, page-size limits, and each user sees only their own scans."""

import breakmyapi.api.main as main
from breakmyapi.models import Scan

SPEC = {"paths": {"/notes": {"get": {}}}}


def add_scan(db, user_id):
    with db() as session:
        scan = Scan(target_url="http://localhost:8001", spec=SPEC, user_id=user_id)
        session.add(scan)
        session.commit()
        return scan.id


def test_page_size_above_the_maximum_is_rejected(priya):
    assert priya.get("/scans", params={"limit": main.MAX_PAGE_SIZE + 1}).status_code == 422


def test_page_size_of_zero_is_rejected(priya):
    assert priya.get("/scans", params={"limit": 0}).status_code == 422


def test_negative_offset_is_rejected(priya):
    assert priya.get("/scans", params={"offset": -1}).status_code == 422


def test_scans_need_a_login(db):
    from fastapi.testclient import TestClient

    anonymous = TestClient(main.app)
    assert anonymous.get("/scans").status_code == 401
    assert anonymous.post("/scans", json={"target_url": "http://localhost:8001", "spec": "x"}).status_code == 401


def test_history_shows_only_your_own_scans(db, priya, rahul):
    add_scan(db, priya.user_id)
    add_scan(db, priya.user_id)
    add_scan(db, rahul.user_id)

    assert priya.get("/scans").json()["total"] == 2
    assert rahul.get("/scans").json()["total"] == 1


def test_someone_elses_scan_looks_exactly_like_a_missing_one(db, priya, rahul):
    scan_id = add_scan(db, priya.user_id)
    missing = "00000000-0000-0000-0000-000000000000"

    assert priya.get(f"/scans/{scan_id}").status_code == 200
    for path in [f"/scans/{scan_id}", f"/scans/{scan_id}/stream"]:
        theirs, nothing = rahul.get(path), rahul.get(path.replace(str(scan_id), missing))
        assert theirs.status_code == nothing.status_code == 404
        assert theirs.json() == nothing.json()  # same answer: Rahul can't even tell it exists


def test_you_cannot_cancel_someone_elses_scan(db, priya, rahul):
    scan_id = add_scan(db, priya.user_id)
    assert rahul.post(f"/scans/{scan_id}/cancel").status_code == 404
    assert priya.get(f"/scans/{scan_id}").json()["status"] == "queued"  # untouched


def test_old_scans_without_an_owner_are_visible_to_nobody(db, priya):
    scan_id = add_scan(db, None)
    assert priya.get(f"/scans/{scan_id}").status_code == 404
