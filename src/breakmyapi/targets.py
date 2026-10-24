"""Safety rule: BreakMyAPI only scans targets on an allowlist.

A scanner sends real requests to whatever URL it is given. Without this check, anyone could
point it at a website they don't own, or at machines inside our own network.

We compare ORIGINS, not whole URLs. An origin is scheme + host + port:
    "http://LOCALHOST:8001/notes?x=1"  ->  "http://localhost:8001"
    "https://example.com"              ->  "https://example.com:443"   (443 is the https default)
"""

import uuid
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from breakmyapi.config import get_settings
from breakmyapi.ownership import is_verified

DEFAULT_PORTS = {"http": 80, "https": 443}  # the only schemes we accept, and their default ports


class TargetError(ValueError):
    """The target URL is broken (missing host, wrong scheme, ...)."""


class TargetNotAllowed(TargetError):
    """The target URL is fine, but it is not on the allowlist."""


def origin_of(url: str) -> str:
    """Turn any URL into its origin, "scheme://host:port", or raise TargetError if it is not usable."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port  # reading .port raises ValueError for nonsense like ":99999" or ":abc"
    except ValueError as e:
        raise TargetError(f"Not a valid URL: {url}") from e

    if parts.scheme not in DEFAULT_PORTS:
        raise TargetError("The target must start with http:// or https://")
    if not parts.hostname:
        raise TargetError("The target URL has no host")
    if parts.username is not None or parts.password is not None:
        # "http://localhost:8001@evil.com" LOOKS like localhost, but the real host is evil.com.
        raise TargetError("The target URL must not contain a username or password")

    return f"{parts.scheme}://{parts.hostname}:{port or DEFAULT_PORTS[parts.scheme]}"


def allowed_origins() -> set[str]:
    """The allowlist from the settings, cleaned the same way, so both sides compare fairly."""
    return {origin_of(o) for o in get_settings().allowed_targets.split(",") if o.strip()}


def check_target(url: str, session: Session | None = None, user_id: uuid.UUID | None = None) -> None:
    """Raise TargetError if the URL is broken, or TargetNotAllowed if we may not scan it.

    A target may be scanned if it is on the allowlist, OR this user has verified it
    (that needs the database and the user). Without them only the allowlist counts:
    forgetting them makes the check stricter, never looser ("fail closed").
    """
    origin = origin_of(url)
    if origin in allowed_origins():
        return
    if session is not None and user_id is not None and is_verified(session, origin, user_id):
        return
    raise TargetNotAllowed(
        f"{origin} is not on the list of allowed targets, and its ownership has not been verified"
    )
