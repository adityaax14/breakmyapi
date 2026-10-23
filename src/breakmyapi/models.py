import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_url: Mapped[str] = mapped_column(String(2048))
    # queued -> running -> completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # JSONB in Postgres; plain JSON in SQLite, which the tests use (CI has no Postgres).
    spec: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanEvent(Base):
    """One line in a scan's diary: what happened, and when."""

    __tablename__ = "scan_events"

    id: Mapped[int] = mapped_column(primary_key=True)  # 1, 2, 3 ... in the order they were written
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TargetClaim(Base):
    """Someone says "I own this API". They prove it by putting `token` on their server.

    verified_at is empty until the proof was found; from then on, that origin may be scanned.
    """

    __tablename__ = "target_claims"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(String(300), index=True)  # e.g. "https://api.example.com:443"
    token: Mapped[str] = mapped_column(String(100))  # the random secret they must publish
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageCounter(Base):
    """How many times one client used one limited feature on one day, e.g. ("ask:203.0.113.7", 2026-10-22) -> 12."""

    __tablename__ = "usage_counters"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
