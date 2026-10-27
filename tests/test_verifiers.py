"""Tests for the real checks: the probe (sends one request) and the missing_auth verifier.

A tiny local HTTP server plays the part of the target. It is allowlisted (127.0.0.1:8001-style
origins), so the probe reaches it directly, like the real notes_target.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from breakmyapi.agent import probe, verifiers
from breakmyapi.agent.probe import ProbeResult
from breakmyapi.targets import TargetNotAllowed


# ---- a fake target we fully control ----


class Handler(BaseHTTPRequestHandler):
    # routes[(method, path)] = status code to return
    routes: dict = {}
    # bodies[(method, path)] = raw response body (bytes); default depends on the status
    bodies: dict = {}

    def _reply(self):
        # Drain the request body if there is one, so keep-alive connections stay clean for
        # requests that send JSON (PATCH/PUT/POST probes).
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        status = self.routes.get((self.command, self.path), 404)
        default_body = b'{"ok": true}' if 200 <= status < 300 else b'{"detail": "no"}'
        body = self.bodies.get((self.command, self.path), default_body)
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_DELETE = _reply

    def log_message(self, *args):
        pass


@pytest.fixture
def target():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Handler.routes = {}
    Handler.bodies = {}
    # The probe checks the origin against the allowlist, so point the allowlist at this server.
    origin = f"http://127.0.0.1:{server.server_port}"
    import breakmyapi.targets as targets
    targets.get_settings.cache_clear()
    yield origin, Handler.routes, Handler.bodies
    server.shutdown()


@pytest.fixture(autouse=True)
def allow_target(target, monkeypatch):
    origin, _, _ = target
    monkeypatch.setattr("breakmyapi.agent.probe.allowed_origins", lambda: {origin})


# ---- fill_path ----


@pytest.mark.parametrize(
    ("path", "filled"),
    [
        ("/notes", "/notes"),
        ("/notes/{note_id}", "/notes/1"),
        ("/users/{user_id}/notes/{note_id}", "/users/1/notes/1"),
    ],
)
def test_fill_path(path, filled):
    assert probe.fill_path(path) == filled


# ---- the probe sends one request and reports the status ----


def test_probe_returns_the_status_code(target):
    origin, routes, _ = target
    routes[("GET", "/notes")] = 200
    result = probe.send(origin, "GET", "/notes")
    assert result.status == 200 and result.error is None


def test_probe_fills_path_parameters(target):
    origin, routes, _ = target
    routes[("GET", "/notes/1")] = 200  # the probe must turn {note_id} into 1
    assert probe.send(origin, "GET", "/notes/{note_id}").status == 200


def test_probe_reports_an_unreachable_target(monkeypatch):
    # Nothing is listening on this port; the probe returns an error, it does not raise.
    monkeypatch.setattr("breakmyapi.agent.probe.allowed_origins", lambda: {"http://127.0.0.1:9"})
    result = probe.send("http://127.0.0.1:9", "GET", "/notes")
    assert result.status is None and "could not reach" in result.error


def test_probe_refuses_an_origin_that_is_not_allowed(monkeypatch):
    # A public origin that is NOT allowlisted goes through the SSRF guard, which blocks a
    # name that resolves to a private address.
    from breakmyapi.netguard import BlockedAddress

    def blocked(host, port):
        raise BlockedAddress("points to a private or internal address")

    monkeypatch.setattr("breakmyapi.agent.probe.allowed_origins", lambda: set())
    monkeypatch.setattr("breakmyapi.netguard.resolve_public", blocked)
    with pytest.raises(TargetNotAllowed):
        probe.send("http://internal.example.com", "GET", "/notes")


# ---- the missing_auth verifier decides pass / fail ----


def send_result(monkeypatch, status, body="", error=None):
    monkeypatch.setattr(probe, "send", lambda *a, **k: ProbeResult(status, body, error))


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (401, "pass"),          # correctly refuses
        (403, "pass"),          # also a refusal
        (200, "fail"),          # answered without a token: the bug
        (204, "fail"),
        (404, "needs_review"),  # unclear
        (500, "needs_review"),
    ],
)
def test_missing_auth_maps_status_to_outcome(monkeypatch, status, outcome):
    send_result(monkeypatch, status)
    assert verifiers.check_missing_auth("http://t", {"method": "GET", "path": "/notes"})[0] == outcome


def test_missing_auth_reports_an_unreachable_target(monkeypatch):
    send_result(monkeypatch, None, error="could not reach the target: ConnectError")
    outcome, note = verifiers.check_missing_auth("http://t", {"method": "GET", "path": "/notes"})
    assert outcome == "error" and "could not reach" in note


# ---- run_test: dispatch, and real end-to-end against the fake target ----


def test_run_test_leaves_unbuilt_checks_as_not_run():
    outcome, note = verifiers.run_test("http://t", {"check": "leaky_errors", "method": "GET", "path": "/x"})
    assert outcome == "not_run" and note == "this check is not built yet"


def test_run_test_catches_a_refusal(monkeypatch):
    def refuse(*a, **k):
        raise TargetNotAllowed("private address")

    monkeypatch.setattr(probe, "send", refuse)
    outcome, note = verifiers.run_test("http://t", {"check": "missing_auth", "method": "GET", "path": "/x"})
    assert outcome == "error" and "refused to send" in note


def test_missing_auth_end_to_end_against_the_fake_target(target):
    origin, routes, _ = target
    routes[("GET", "/public")] = 200   # a vulnerable endpoint: answers with no token
    routes[("GET", "/private")] = 401  # a safe endpoint: refuses

    bad = verifiers.run_test(origin, {"check": "missing_auth", "method": "GET", "path": "/public"})
    good = verifiers.run_test(origin, {"check": "missing_auth", "method": "GET", "path": "/private"})
    assert bad[0] == "fail"
    assert good[0] == "pass"


# ---- the object_level_access verifier ----


def test_without_a_test_token_the_result_is_needs_review():
    test = {"check": "object_level_access", "method": "GET", "path": "/notes/{note_id}"}
    outcome, note = verifiers.check_object_level_access("http://t", test, None)
    assert outcome == "needs_review" and "test token" in note


def test_collection_path_of():
    assert verifiers.collection_path_of("/notes/{note_id}") == "/notes"
    assert verifiers.collection_path_of("/users/{user_id}/notes/{note_id}") == "/users/{user_id}/notes"
    assert verifiers.collection_path_of("/notes") is None  # no trailing {id} to strip


def test_owned_ids_reads_id_fields_from_a_json_list():
    assert verifiers.owned_ids('[{"id": 1, "title": "a"}, {"id": 2}]') == {"1", "2"}
    assert verifiers.owned_ids('{"items": [{"id": 7}]}') == {"7"}
    assert verifiers.owned_ids("not json") == set()
    assert verifiers.owned_ids("[]") == set()


def test_bola_fails_when_a_foreign_object_id_is_readable(target):
    origin, routes, bodies = target
    routes[("GET", "/notes")] = 200
    bodies[("GET", "/notes")] = b'[{"id": 1}]'  # our own account owns only note 1
    routes[("GET", "/notes/2")] = 200           # but note 2 (not ours) is ALSO readable: the bug

    outcome, note = verifiers.check_object_level_access(
        origin, {"check": "object_level_access", "method": "GET", "path": "/notes/{note_id}"}, "tok123"
    )
    assert outcome == "fail"
    assert "/notes/2" in note


def test_bola_passes_when_foreign_ids_are_all_refused(target):
    origin, routes, bodies = target
    routes[("GET", "/notes")] = 200
    bodies[("GET", "/notes")] = b'[{"id": 1}]'
    for other_id in ["2", "3", "4", "5"]:
        routes[("GET", f"/notes/{other_id}")] = 404  # correctly not found / not ours

    outcome, _ = verifiers.check_object_level_access(
        origin, {"check": "object_level_access", "method": "GET", "path": "/notes/{note_id}"}, "tok123"
    )
    assert outcome == "pass"


def test_bola_sends_the_test_token_on_every_request(target):
    origin, routes, _ = target
    routes[("GET", "/notes")] = 200
    routes[("GET", "/notes/1")] = 404
    seen_auth = []
    real_send = probe.send

    def spying_send(target_url, method, path, headers=None):
        seen_auth.append((headers or {}).get("Authorization"))
        return real_send(target_url, method, path, headers=headers)

    import breakmyapi.agent.verifiers as v
    orig = v.probe.send
    v.probe.send = spying_send
    try:
        verifiers.check_object_level_access(
            origin, {"check": "object_level_access", "method": "GET", "path": "/notes/{note_id}"}, "secret-tok"
        )
    finally:
        v.probe.send = orig
    assert seen_auth and all(a == "Bearer secret-tok" for a in seen_auth)


def test_run_test_passes_the_token_through_for_object_level_access(target):
    origin, routes, bodies = target
    routes[("GET", "/notes")] = 200
    bodies[("GET", "/notes")] = b"[]"
    routes[("GET", "/notes/1")] = 404

    outcome, _ = verifiers.run_test(
        origin, {"check": "object_level_access", "method": "GET", "path": "/notes/{note_id}"}, "tok"
    )
    assert outcome == "pass"


def test_run_test_without_a_token_argument_defaults_to_needs_review(target):
    origin, _, _ = target
    outcome, _ = verifiers.run_test(
        origin, {"check": "object_level_access", "method": "GET", "path": "/notes/{note_id}"}
    )
    assert outcome == "needs_review"


# ---- the mass_assignment verifier ----


def test_mass_assignment_fails_when_the_field_is_echoed_back(target):
    origin, routes, bodies = target
    routes[("PATCH", "/users/me")] = 200
    bodies[("PATCH", "/users/me")] = b'{"id": 1, "role": "admin"}'  # echoed our injected value

    outcome, note = verifiers.check_mass_assignment(
        origin, {"method": "PATCH", "path": "/users/me"}, "tok"
    )
    assert outcome == "fail" and "role" in note


def test_mass_assignment_passes_when_the_field_is_ignored(target):
    origin, routes, bodies = target
    routes[("PATCH", "/users/me")] = 200
    bodies[("PATCH", "/users/me")] = b'{"id": 1, "role": "user"}'  # our value was NOT applied

    outcome, _ = verifiers.check_mass_assignment(origin, {"method": "PATCH", "path": "/users/me"}, "tok")
    assert outcome == "pass"


def test_mass_assignment_is_inconclusive_when_every_attempt_is_rejected(target):
    origin, routes, _ = target
    routes[("PATCH", "/users/me")] = 422  # looks like we're missing required fields, not a verdict

    outcome, _ = verifiers.check_mass_assignment(origin, {"method": "PATCH", "path": "/users/me"}, "tok")
    assert outcome == "needs_review"


def test_mass_assignment_stops_at_the_first_fail_without_trying_every_field(target):
    origin, routes, bodies = target
    routes[("PATCH", "/users/me")] = 200
    bodies[("PATCH", "/users/me")] = b'{"role": "admin"}'  # the FIRST probed field already succeeds
    calls = []
    real_send = probe.send
    probe.send = lambda *a, **k: (calls.append(k.get("json")), real_send(*a, **k))[1]
    try:
        verifiers.check_mass_assignment(origin, {"method": "PATCH", "path": "/users/me"}, "tok")
    finally:
        probe.send = real_send
    # One GET to read the current object (no json body -> None), then ONE probe: stopped at the first fail.
    assert calls == [None, {"role": "admin"}]


def test_run_test_dispatches_mass_assignment_with_the_token(target):
    origin, routes, bodies = target
    routes[("PATCH", "/users/me")] = 200
    bodies[("PATCH", "/users/me")] = b'{"role": "user"}'
    outcome, _ = verifiers.run_test(origin, {"check": "mass_assignment", "method": "PATCH", "path": "/users/me"}, "tok")
    assert outcome == "pass"


def test_mass_assignment_patch_resends_the_current_object_plus_the_extra_field(target):
    # The GET returns the object's real fields; the PATCH probe should include them (so a strict
    # schema with required fields does not reject the body), plus the one injected privileged field.
    origin, routes, bodies = target
    routes[("GET", "/users/me")] = 200
    bodies[("GET", "/users/me")] = b'{"id": 1, "display_name": "Alice", "role": "user"}'
    routes[("PATCH", "/users/me")] = 200
    bodies[("PATCH", "/users/me")] = b'{"role": "user"}'  # safe: our injected value was not applied

    sent = []
    real_send = probe.send
    probe.send = lambda *a, **k: (sent.append(k.get("json")), real_send(*a, **k))[1]
    try:
        verifiers.check_mass_assignment(origin, {"method": "PATCH", "path": "/users/me"}, "tok")
    finally:
        probe.send = real_send

    assert sent[0] is None  # the GET
    first_probe = sent[1]
    assert first_probe["display_name"] == "Alice"  # real field carried over
    assert "id" not in first_probe                 # the id is dropped (never resent)
    assert first_probe["role"] == "admin"          # the injected privileged value


# ---- the excessive_data verifier ----


def test_excessive_data_fails_when_a_sensitive_field_leaks(target):
    origin, routes, bodies = target
    routes[("GET", "/users/me")] = 200
    bodies[("GET", "/users/me")] = b'{"id": 1, "username": "alice", "password_hash": "abc123"}'
    outcome, note = verifiers.check_excessive_data(origin, {"method": "GET", "path": "/users/me"}, "tok")
    assert outcome == "fail" and "password_hash" in note


def test_excessive_data_passes_when_only_safe_fields_are_returned(target):
    origin, routes, bodies = target
    routes[("GET", "/users/me")] = 200
    bodies[("GET", "/users/me")] = b'{"id": 1, "username": "alice", "display_name": "Alice"}'
    outcome, _ = verifiers.check_excessive_data(origin, {"method": "GET", "path": "/users/me"}, "tok")
    assert outcome == "pass"


def test_excessive_data_finds_sensitive_fields_nested_and_in_lists():
    assert verifiers.sensitive_fields_in({"user": {"secret": "x"}}) == {"secret"}
    assert verifiers.sensitive_fields_in([{"ssn": "1"}, {"name": "ok"}]) == {"ssn"}
    assert verifiers.sensitive_fields_in({"userPassword": "x"}) == {"userPassword"}  # case-insensitive match
    assert verifiers.sensitive_fields_in({"display_name": "fine"}) == set()


def test_excessive_data_is_needs_review_on_non_json_or_error_status(target):
    origin, routes, bodies = target
    routes[("GET", "/x")] = 200
    bodies[("GET", "/x")] = b"not json at all"
    assert verifiers.check_excessive_data(origin, {"method": "GET", "path": "/x"}, "tok")[0] == "needs_review"
    routes[("GET", "/y")] = 500
    assert verifiers.check_excessive_data(origin, {"method": "GET", "path": "/y"}, "tok")[0] == "needs_review"
