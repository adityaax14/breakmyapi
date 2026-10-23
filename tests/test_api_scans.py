"""Tests for GET /scans: the page-size limit is enforced before the database is touched."""

from fastapi.testclient import TestClient

import breakmyapi.api.main as main

client = TestClient(main.app)


def test_page_size_above_the_maximum_is_rejected():
    response = client.get("/scans", params={"limit": main.MAX_PAGE_SIZE + 1})
    assert response.status_code == 422


def test_page_size_of_zero_is_rejected():
    assert client.get("/scans", params={"limit": 0}).status_code == 422


def test_negative_offset_is_rejected():
    assert client.get("/scans", params={"offset": -1}).status_code == 422
