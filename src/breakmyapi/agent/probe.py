"""Send ONE request to the target being scanned, and report back what came out.

This is the only place in the agent that actually talks to the user's API. It is deliberately
small and careful:
- it refuses any origin that was not approved (allowlist, or the user's verified target);
- allowlisted LOCAL practice targets (localhost:8001) are reached directly, because the SSRF
  guard blocks private addresses on purpose; any other (public) target goes through the guard;
- one short timeout, no redirects, and the response body is read only up to a small cap.

It never follows links, never retries, and sends exactly the one request it is asked to.
"""

import re

import httpx

from breakmyapi.netguard import guarded_stream
from breakmyapi.targets import TargetNotAllowed, allowed_origins, origin_of

TIMEOUT_SECONDS = 10
MAX_BODY_BYTES = 64 * 1024  # enough to inspect a response; a huge body is cut off here

# Harmless sample values to fill path parameters like /notes/{note_id} so the URL is real.
SAMPLE_PATH_VALUE = "1"


class ProbeResult:
    """What one request produced: a status code and a little of the body, or an error string."""

    def __init__(self, status: int | None, body: str = "", error: str | None = None):
        self.status = status
        self.body = body
        self.error = error


def fill_path(path: str) -> str:
    """Replace every {placeholder} in a path with a harmless sample value.

    "/notes/{note_id}" -> "/notes/1".  The value does not matter for the checks we run:
    we are testing how the endpoint HANDLES a request, not hunting for a specific record.
    """
    return re.sub(r"\{[^}]+\}", SAMPLE_PATH_VALUE, path)


def send(target_url: str, method: str, path: str, headers: dict | None = None, json=None) -> ProbeResult:
    """Send one request to target_url + path and return a ProbeResult.

    `json`, if given, is sent as the request body (a small dict), e.g. {"role": "admin"} for a
    mass-assignment probe. Raises TargetNotAllowed if the origin is not approved (defence in
    depth: run_scan already checked, but this is the last gate before a request leaves us).
    """
    origin = origin_of(target_url)
    allowed = allowed_origins()
    if origin not in allowed:
        # Not a static practice target. The scanner only reaches a non-allowlisted origin through
        # the SSRF guard, which also confirms it is public and pins the IP. If the guard refuses
        # (private/internal address), the request is never sent.
        return _send_guarded(origin, method, path, headers, json)
    return _send_direct(origin, method, path, headers, json)


def _url(origin: str, path: str) -> str:
    return origin + fill_path(path)


def _read_capped(response: httpx.Response) -> str:
    body = b""
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            break
    return body[:MAX_BODY_BYTES].decode("utf-8", errors="replace")


def _send_direct(origin: str, method: str, path: str, headers: dict | None, json=None) -> ProbeResult:
    """Allowlisted local practice target: connect straight to it (the guard would block localhost)."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            with client.stream(method, _url(origin, path), headers=headers or {}, json=json) as response:
                return ProbeResult(response.status_code, _read_capped(response))
    except httpx.HTTPError as e:
        return ProbeResult(None, error=f"could not reach the target: {type(e).__name__}")


def _send_guarded(origin: str, method: str, path: str, headers: dict | None, json=None) -> ProbeResult:
    """Public target: go through the SSRF guard (public addresses only, pinned IP, no redirects)."""
    from breakmyapi.netguard import BlockedAddress

    try:
        with guarded_stream(method, _url(origin, path), timeout=TIMEOUT_SECONDS, headers=headers or {}, json=json) as response:
            return ProbeResult(response.status_code, _read_capped(response))
    except BlockedAddress as e:
        raise TargetNotAllowed(str(e)) from e
    except httpx.HTTPError as e:
        return ProbeResult(None, error=f"could not reach the target: {type(e).__name__}")
