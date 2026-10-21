"""Tests for spec/parser.py: reading an OpenAPI spec into a list of endpoints."""

import pytest

from breakmyapi.spec.parser import SpecError, load_spec, parse_endpoints

SPEC = """
openapi: 3.0.3
security:
  - bearerAuth: []
paths:
  /login:
    post:
      security: []
      requestBody: {}
  /notes/{note_id}:
    get: {}
    patch:
      requestBody: {}
  /admin/users:
    get:
      tags: [admin]
"""


def endpoint(method: str, path: str):
    """Find one endpoint in the parsed sample spec."""
    return next(e for e in parse_endpoints(load_spec(SPEC)) if e.method == method and e.path == path)


def test_finds_every_method_on_every_path():
    assert len(parse_endpoints(load_spec(SPEC))) == 4


def test_login_does_not_need_auth():
    assert endpoint("POST", "/login").requires_auth is False


def test_other_endpoints_inherit_the_global_auth_rule():
    assert endpoint("GET", "/notes/{note_id}").requires_auth is True


def test_id_in_path_is_detected():
    assert endpoint("GET", "/notes/{note_id}").has_path_id is True
    assert endpoint("POST", "/login").has_path_id is False


def test_request_body_is_detected():
    assert endpoint("PATCH", "/notes/{note_id}").accepts_body is True
    assert endpoint("GET", "/notes/{note_id}").accepts_body is False


def test_admin_route_is_detected():
    assert endpoint("GET", "/admin/users").is_admin is True


@pytest.mark.parametrize("bad_text", ["hello", "paths: [unclosed", "openapi: 3.0.3"])
def test_bad_specs_are_rejected(bad_text):
    with pytest.raises(SpecError):
        load_spec(bad_text)


def test_empty_path_is_skipped_instead_of_crashing():
    # This spec once caused a 500 error (Lesson 8 warm-up): "/notes:" has nothing under it.
    spec = load_spec("openapi: 3.0.3\npaths:\n  /notes:\n")
    assert parse_endpoints(spec) == []
