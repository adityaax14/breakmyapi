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
    #                  \-> waiting_approval -> (user answers) -> queued -> running -> ...
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # While waiting: the tests the agent wants permission for (shown in the UI). Afterwards: kept for the record.
    approval_request: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # The user's answer: "approve" or "reject" (empty until they answer).
    approval: Mapped[str | None] = mapped_column(String(20))
    # The user's framework, so fix advice is written for it: generic, fastapi, django, express, spring.
    framework: Mapped[str] = mapped_column(String(20), default="generic", server_default="generic")
    # The finished report: {"summary": "...", "sections": [...]}. Empty until the scan completes.
    report: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # Optional: a bearer token for a THROWAWAY test account on the target, so checks that need
    # to be logged in (object-level access, mass assignment...) can run. Never required.
    test_token: Mapped[str | None] = mapped_column(String(2000))
    # JSONB in Postgres; plain JSON in SQLite, which the tests use (CI has no Postgres).
    spec: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # Who started it. Empty only for old scans made before accounts existed (nobody can see those).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanEvent(Base):
    """One line in a scan's diary: what happened, and when."""

    __tablename__ = "scan_events"

    id: Mapped[int] = mapped_column(primary_key=True)  # 1, 2, 3 ... in the order they were written
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # unique: one account per email
    # NEVER the password itself: a one-way Argon2 hash of it (see auth.py).
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """One logged-in device. The browser holds a random token; we keep only its SHA-256 hash."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TargetClaim(Base):
    """Someone says "I own this API". They prove it by putting `token` on their server.

    verified_at is empty until the proof was found; from then on, that origin may be scanned.
    """

    __tablename__ = "target_claims"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(String(300), index=True)  # e.g. "https://api.example.com:443"
    token: Mapped[str] = mapped_column(String(100))  # the random secret they must publish
    # Whose claim it is. A verified site may be scanned only by the user who verified it.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageCounter(Base):
    """How many times one client used one limited feature on one day, e.g. ("ask:203.0.113.7", 2026-10-22) -> 12."""

    __tablename__ = "usage_counters"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
