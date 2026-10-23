"""Ownership verification: prove you control an API before BreakMyAPI may scan it.

The same idea Google Search Console and Let's Encrypt use:
  1. You ask to scan https://api.example.com. We create a claim with a random secret (the token).
  2. You publish that token on your server at  https://api.example.com/.well-known/breakmyapi-verify.txt
  3. We fetch that file. If it contains the token, only someone who controls the server could
     have put it there, so the claim is marked verified and the origin may be scanned.
"""

import secrets

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from breakmyapi.models import TargetClaim
from breakmyapi.netguard import guarded_stream

PROOF_PATH = "/.well-known/breakmyapi-verify.txt"  # /.well-known/ is the standard folder for files like this
MAX_PROOF_BYTES = 1024  # the token is ~50 characters; never download more than this
TIMEOUT_SECONDS = 5


def new_token() -> str:
    """A random secret nobody can guess, e.g. "breakmyapi-Xq3v9...". (secrets = randomness safe for security.)"""
    return "breakmyapi-" + secrets.token_urlsafe(24)


def proof_url(origin: str) -> str:
    return origin + PROOF_PATH


def fetch_proof(url: str) -> str | None:
    """Download the proof file. Returns its text, or None if it could not be read safely.

    Careful, because this request goes to an address a stranger typed in:
    - the SSRF guard: public addresses only, pinned, no redirects (raises BlockedAddress otherwise)
    - a short timeout, so a slow server cannot hold us up
    - at most 1 KB, so a huge file cannot fill our memory
    """
    try:
        with guarded_stream("GET", url, timeout=TIMEOUT_SECONDS) as response:
            if response.status_code != 200:
                return None
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_PROOF_BYTES:
                    return None
            return body.decode("utf-8", errors="replace").strip()
    except httpx.HTTPError:
        return None  # could not connect, timed out, ...


def proof_matches(found: str | None, token: str) -> bool:
    """Is the file's text exactly our token?

    compare_digest takes the same time whether the first or the last character differs,
    so an attacker cannot guess the token one character at a time by measuring our speed.
    """
    return found is not None and secrets.compare_digest(found.encode(), token.encode())


def is_verified(session: Session, origin: str) -> bool:
    """Has anyone proved ownership of this origin?"""
    claim_id = session.scalar(
        select(TargetClaim.id)
        .where(TargetClaim.origin == origin, TargetClaim.verified_at.is_not(None))
        .limit(1)
    )
    return claim_id is not None
 