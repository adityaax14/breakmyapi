from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from breakmyapi.config import get_settings
from breakmyapi.models import Base

engine = create_engine(get_settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


# create_all() makes MISSING tables, but never changes a table that already exists. These add the
# columns that came later to databases created before them. "IF NOT EXISTS" makes them safe to run
# on every start. (A real migration tool, such as Alembic, does this properly; that comes later.)
MIGRATIONS = [
    "ALTER TABLE scans ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS ix_scans_user_id ON scans (user_id)",
    "ALTER TABLE target_claims ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS ix_target_claims_user_id ON target_claims (user_id)",
]


def init_db() -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:  # begin(): all of them are saved together, or none
            for statement in MIGRATIONS:
                connection.execute(text(statement))


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
