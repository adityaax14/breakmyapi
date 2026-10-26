"""One verifier per check type: run the test, and decide pass / fail / needs_review.

A verifier takes the target URL and the planned test, sends the needed request(s) through
probe.py, and returns (outcome, note):
  - "pass"          the endpoint behaved safely
  - "fail"          the weakness is present
  - "needs_review"  the result is unclear and a human should look
  - "error"         the target could not be reached

Only check types with a verifier here are actually run. Anything else stays "not built yet".
"""

import json
import re
from collections.abc import Callable

from breakmyapi.agent import probe
from breakmyapi.targets import TargetNotAllowed

# How many extra object ids we are willing to probe for one object-level-access test.
# Keeps the request count small and bounded, like a page-size limit.
BOLA_PROBE_IDS = ["1", "2", "3", "4", "5"]


def check_missing_auth(target_url: str, test: dict) -> tuple[str, str]:
    """The endpoint claims to need a login. Send the request with NO token and see what happens.

    A safe endpoint refuses (401 or 403). A vulnerable one answers anyway (2xx): it forgot to
    check the token. We send no body, so even a vulnerable write endpoint changes nothing.
    """
    result = probe.send(target_url, test["method"], test["path"], headers={})  # no Authorization header

    if result.error:
        return "error", result.error
    if result.status in (401, 403):
        return "pass", f"returned {result.status} to a request with no token, as it should"
    if 200 <= result.status < 300:
        return "fail", (
            f"returned {result.status} to a request with NO login token: this endpoint answers "
            "unauthenticated callers, so its authentication is not enforced"
        )
    return "needs_review", f"returned {result.status} to a request with no token (expected 401 or 403)"


def collection_path_of(item_path: str) -> str | None:
    """"/notes/{note_id}" -> "/notes" (the list endpoint for this kind of object), or None if the
    path has no final {id} segment to strip."""
    collection = re.sub(r"/\{[^/}]+\}$", "", item_path)
    return collection if collection != item_path else None


def owned_ids(body: str) -> set[str]:
    """Best-effort: pull every "id" field out of a JSON list response, as strings.

    This is read-only inspection of OUR OWN account's data (the list endpoint, with our own
    token), used only to know which ids are already known to be ours, so we do not count them
    as a finding when probing nearby ids.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return set()
    items = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
    return {str(item["id"]) for item in items if isinstance(item, dict) and "id" in item}


def check_object_level_access(target_url: str, test: dict, test_token: str | None) -> tuple[str, str]:
    """Logged in as the test account, can we read an object id that is not ours?

    This is OWASP's own lightweight BOLA test (API1:2023): with a single valid session, try
    nearby object ids and see whether the API checks OWNERSHIP, not just whether a token exists.
    We never guess or brute-force credentials; we only use the token the user supplied for
    their own throwaway test account, and we only send GET requests.

    It is a heuristic, not a proof: on a real target we cannot always tell which ids belong to
    someone else, so an inconclusive result is reported as "needs_review" rather than guessed at.
    """
    if not test_token:
        return "needs_review", (
            "could not check: this needs a test token for a logged-in account (see the scan form)"
        )
    auth = {"Authorization": f"Bearer {test_token}"}

    mine: set[str] = set()
    collection = collection_path_of(test["path"])
    if collection:
        listing = probe.send(target_url, "GET", collection, headers=auth)
        if listing.status == 200:
            mine = owned_ids(listing.body)

    candidates = [i for i in BOLA_PROBE_IDS if i not in mine]
    if not candidates:
        return "needs_review", "could not find an object id to test that is not already our own"

    for object_id in candidates:
        path = re.sub(r"\{[^/}]+\}$", object_id, test["path"])
        result = probe.send(target_url, test["method"], path, headers=auth)
        if result.error:
            continue  # try the next candidate rather than failing the whole test on one network hiccup
        if 200 <= result.status < 300:
            return "fail", (
                f"returned {result.status} for {test['method']} {path} using our test account's token, "
                f"although that object id was not in our own account's list: ownership is not enforced"
            )

    return "pass", (
        f"tried {len(candidates)} object id(s) not in our own account and none were accessible "
        "with our test account's token, as expected"
    )


# Privileged-looking fields a client should never be able to set on itself. Each is tried with
# a harmless-looking escalation value, one field per request, so a vulnerable endpoint is caught
# without us needing to know the target's real schema.
MASS_ASSIGNMENT_PROBES = [
    ("role", "admin"),
    ("is_admin", True),
    ("admin", True),
    ("is_verified", True),
]


def current_object(target_url: str, test: dict, auth: dict) -> dict:
    """GET the object this test is about to update, so our probe body can piggyback real data
    instead of sending a lone field that a normal, strict schema would reject as incomplete.

    Best-effort: on any failure this returns {}, and the probe falls back to sending the
    extra field alone (still useful, just more likely to be inconclusive on strict endpoints).
    """
    result = probe.send(target_url, "GET", test["path"], headers=auth)
    if result.status != 200:
        return {}
    try:
        data = json.loads(result.body)
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if k != "id"} if isinstance(data, dict) else {}


def check_mass_assignment(target_url: str, test: dict, test_token: str | None) -> tuple[str, str]:
    """Send a body with one extra, privileged field the client should not be able to set.

    If the field comes back echoed in the response with OUR value, the endpoint accepted it:
    it is binding the request body onto an internal object instead of only the allowed fields
    (OWASP API3/API6). A 4xx (validation error) is inconclusive, not a pass — but for PATCH/PUT
    we first fetch the object's CURRENT fields and send those back alongside our extra field, so
    a strict schema with other required fields does not sink the whole test on an incomplete body.
    """
    auth = {"Authorization": f"Bearer {test_token}"} if test_token else {}
    base = current_object(target_url, test, auth) if test["method"] in ("PATCH", "PUT") else {}
    saw_any_success = False

    for field, value in MASS_ASSIGNMENT_PROBES:
        body = {**base, field: value}
        result = probe.send(target_url, test["method"], test["path"], headers=auth, json=body)
        if result.error:
            continue
        if not (200 <= result.status < 300):
            continue  # rejected outright (missing required fields we still don't know about): inconclusive
        saw_any_success = True

        try:
            data = json.loads(result.body)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get(field) == value:
            return "fail", (
                f"sending {{\"{field}\": {value!r}}} in the body was accepted and echoed back: "
                "a client can set a field it should not control"
            )

    if saw_any_success:
        return "pass", "privileged fields in the request body were accepted but not applied, as expected"
    return "needs_review", "could not get a successful response to judge whether extra fields are accepted"


# Field names that should essentially never appear in a response sent to a client. Matched as a
# substring of a key, case-insensitively, so "password_hash" and "userPassword" both hit "password".
SENSITIVE_FIELD_NAMES = [
    "password", "passwd", "pwd", "password_hash", "pwhash",
    "secret", "private_key", "privatekey", "ssn", "social_security",
    "card_number", "cardnumber", "cvv", "security_code",
]


def sensitive_fields_in(data: object, found: set[str] | None = None) -> set[str]:
    """Walk a parsed JSON value (dict / list / nested) and collect every KEY whose name looks
    like it leaks a secret. Read-only inspection of the response we already received."""
    found = set() if found is None else found
    if isinstance(data, dict):
        for key, value in data.items():
            low = key.lower()
            if any(bad in low for bad in SENSITIVE_FIELD_NAMES):
                found.add(key)
            sensitive_fields_in(value, found)  # recurse into nested objects
    elif isinstance(data, list):
        for item in data:
            sensitive_fields_in(item, found)
    return found


def check_excessive_data(target_url: str, test: dict, test_token: str | None) -> tuple[str, str]:
    """GET the endpoint and see whether the response hands back fields that should never leave the
    server, such as a password hash (OWASP API3:2023 excessive data exposure).

    We only READ the response; we send nothing. A token is used if given, so authenticated
    endpoints (like /users/me) can be reached; without one we can still check public endpoints.
    """
    auth = {"Authorization": f"Bearer {test_token}"} if test_token else {}
    result = probe.send(target_url, "GET", test["path"], headers=auth)

    if result.error:
        return "error", result.error
    if not (200 <= result.status < 300):
        return "needs_review", f"returned {result.status}; no response body to inspect for leaked fields"
    try:
        data = json.loads(result.body)
    except ValueError:
        return "needs_review", "the response was not JSON, so its fields could not be inspected"

    leaked = sensitive_fields_in(data)
    if leaked:
        return "fail", (
            f"the response includes sensitive field(s) that should not be sent to a client: "
            f"{', '.join(sorted(leaked))}"
        )
    return "pass", "the response did not contain any obviously sensitive fields"


# The checks that are actually built. The rest stay "not built yet" until they are added here.
VERIFIERS: dict[str, Callable] = {
    "missing_auth": check_missing_auth,
    "object_level_access": check_object_level_access,
    "mass_assignment": check_mass_assignment,
    "excessive_data": check_excessive_data,
}

# Which verifiers need the (optional) test token passed in, beyond (target_url, test).
NEEDS_TOKEN = {"object_level_access", "mass_assignment", "excessive_data"}


def run_test(target_url: str, test: dict, test_token: str | None = None) -> tuple[str, str]:
    """Run one planned test if its check type is built; otherwise say so. Never raises."""
    verifier = VERIFIERS.get(test["check"])
    if verifier is None:
        return "not_run", "this check is not built yet"
    try:
        if test["check"] in NEEDS_TOKEN:
            return verifier(target_url, test, test_token)
        return verifier(target_url, test)
    except TargetNotAllowed as e:
        return "error", f"refused to send: {e}"
    except Exception as e:  # a bug in a verifier must never crash the whole scan
        return "error", f"the check could not run: {type(e).__name__}"
