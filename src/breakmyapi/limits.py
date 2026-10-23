"""Daily limits for endpoints that cost money, such as POST /library/ask (every question is an LLM call)."""

from datetime import UTC, date, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from breakmyapi.config import get_settings
from breakmyapi.db import get_session
from breakmyapi.models import UsageCounter


def count_use(session: Session, key: str, day: date) -> int:
    """Add 1 to this key's counter for this day, and return the new total.

    One SQL statement does both ("insert a row with 1, or if the row exists, add 1"),
    so two requests arriving at the same moment can never both read 29 and both write 30.
    """
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
