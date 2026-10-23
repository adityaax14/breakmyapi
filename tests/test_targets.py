"""Tests for the target allowlist: the safety rule that decides what may be scanned.

The default allowlist (config.py) is http://localhost:8001 and http://127.0.0.1:8001.
"""

import pytest
from fastapi.testclient import TestClient

import breakmyapi.api.main as main
from breakmyapi.targets import TargetError, TargetNotAllowed, check_target, origin_of

SPEC = "paths:\n  /notes:\n    get: {}\n"


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("http://localhost:8001", "http://localhost:8001"),
        ("http://localhost:8001/notes?x=1", "http://localhost:8001"),  # the path doesn't matter
        ("HTTP://LOCALHOST:8001", "http://localhost:8001"),            # nor upper/lower case
        ("  http://localhost:8001  ", "http://localhost:8001"),        # nor stray spaces
        ("https://example.com", "https://example.com:443"),            # missing port = the default
        ("http://example.com", "http://example.com:80"),
    ],
)
def test_origin_of(url, origin):
    assert origin_of(url) == origin


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8001",
        "http://127.0.0.1:8001/notes",
        "HTTP://LocalHost:8001/",
    ],
)
def test_allowed_targets_pass(url):
    check_target(url)  # no exception = allowed


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8002",            # right host, wrong port
        "http://localhost",                 # no port = port 80, not 8001
        "https://localhost:8001",           # https is a different origin
        "http://example.com",               # someone else's website
        "http://169.254.169.254:8001",      # cloud "metadata" address: holds secret keys in the cloud
        "http://192.168.1.1:8001",          # a machine on the local network
        "http://localhost.evil.com:8001",   # starts like localhost, but it's a host under evil.com
    ],
)
def test_other_targets_are_not_allowed(url):
    with pytest.raises(TargetNotAllowed):
        check_target(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8001@evil.com",   # the real host here is evil.com
        "http://localhost:8001.evil.com",   # the "port" would be "8001.evil.com": not a number
        "ftp://localhost:8001",             # only http and https
        "file:///etc/passwd",               # reading a file from our own server
        "localhost:8001",                   # no scheme
        "http://localhost:99999",           # not a real port
        "http://",                          # no host
        "",
    ],
)
def test_broken_or_tricky_urls_are_rejected(url):
    with pytest.raises(TargetError):
        check_target(url)


client = TestClient(main.app)


def test_api_refuses_a_target_not_on_the_list(db):
    response = client.post("/scans", json={"target_url": "http://example.com", "spec": SPEC})
    assert response.status_code == 403
    assert "not on the list" in response.json()["detail"]


def test_api_rejects_a_broken_target_url(db):
    response = client.post("/scans", json={"target_url": "ftp://localhost:8001", "spec": SPEC})
    assert response.status_code == 422
