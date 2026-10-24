"""Daily limits for endpoints that cost money, such as POST /library/ask (every question is an LLM call)."""

from datetime import UTC, date, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from breakmyapi.config import get_settings
from breakmyapi.db import get_session
from breakmyapi.models import UsageCounter


def count_use(session: Session, key: str, day: date) -> int:
    """Add 1 to this key's counter for this day, and return the new total.

    One SQL statement does both ("insert a row with 1, or if the row exists, add 1"),
    so two requests arriving at the same moment can never both read 29 and both write 30.
    """
    # Postgres and SQLite (used by the tests) both support "insert, or add 1 if it exists",
    # but each has its own version of insert(). Pick the one for the database we are talking to.
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else postgres_insert
    statement = (
        insert(UsageCounter)
        .values(key=key, day=day, count=1)
        .on_conflict_do_update(index_elements=["key", "day"], set_={"count": UsageCounter.count + 1})
        .returning(UsageCounter.count)
    )
    total = session.execute(statement).scalar_one()
    session.commit()
    return total


def seconds_until_tomorrow(now: datetime) -> int:
    """Seconds until the next midnight (UTC), when every counter starts again from zero."""
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return int((tomorrow - now).total_seconds())


def wait_if_over(session: Session, key: str, limit: int, window_seconds: int, now: datetime | None = None) -> int | None:
    """Count one attempt for `key` in the current time window.

    Returns None if it is allowed, or how many seconds to wait if the limit is used up.

    Time is cut into fixed windows, e.g. 15 minutes: 10:00-10:15, 10:15-10:30, ...
    Each window gets its own counter row, by putting the window's number into the key:
        "login-email:priya@example.com:1981374"   (1981374 = seconds since 1970 // 900)
    so a new window simply starts a new counter at 0. (This is called a "fixed window" limiter.)
    """
    now = now or datetime.now(UTC)
    seconds = int(now.timestamp())
    window = seconds // window_seconds
    window_start = datetime.fromtimestamp(window * window_seconds, UTC)

    used = count_use(session, f"{key}:{window}", window_start.date())
    if used > limit:
        return (window + 1) * window_seconds - seconds  # until the next window starts
    return None


def too_many(wait_seconds: int, message: str) -> HTTPException:
    """The standard "slow down" answer: 429, plus Retry-After saying how long to wait."""
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, message, headers={"Retry-After": str(wait_seconds)}
    )


def client_ip(request: Request) -> str:
    # The address the request came from. NOTE for deployment: behind a proxy or load balancer this
    # is the proxy's address; the real one is then in a header the proxy sets (X-Forwarded-For),
    # which may only be trusted when it comes from OUR proxy.
    return request.client.host if request.client else "unknown"


def limit_asks(request: Request, session: Session = Depends(get_session)) -> None:
    """FastAPI dependency: refuse with 429 once a client has used up today's questions."""
    limit = get_settings().ask_daily_limit
    now = datetime.now(UTC)
    client = request.client.host if request.client else "unknown"

    used = count_use(session, f"ask:{client}", now.date())
    if used > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily limit of {limit} questions reached. It resets at midnight UTC.",
            headers={"Retry-After": str(seconds_until_tomorrow(now))},
        )
