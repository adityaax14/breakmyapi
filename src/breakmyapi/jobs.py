"""A tiny, reliable job queue on Redis: the API puts scan ids in, workers take them out, oldest first.

Why a queue: the API should answer in milliseconds, while a scan can take minutes. The API
only records the job; a separate worker program does the slow work.

Reliability ("at least once"): a worker does not just take a job out of the line. It MOVES the
job into its own "in progress" list, and removes it from there only when the scan is finished.
If the worker crashes halfway, the job is still in its in-progress list, and the worker puts it
back in the line when it starts again.
"""

import uuid
from functools import lru_cache

import redis

from breakmyapi.config import get_settings

QUEUE = "scans:queue"  # the line of waiting scan ids
WAIT_SECONDS = 5       # how long next_scan() waits for a job before giving up and looping again


@lru_cache
def get_redis() -> redis.Redis:
    # socket_timeout must be LONGER than WAIT_SECONDS: while Redis holds the connection open
    # waiting for a job, the client must not give up first (redis-py's default is 5 s, a tie).
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_timeout=WAIT_SECONDS + 25)


def in_progress(worker: str) -> str:
    """The name of one worker's own in-progress list, e.g. "scans:processing:worker-1"."""
    return f"scans:processing:{worker}"


def enqueue_scan(scan_id: uuid.UUID) -> None:
    """Add a scan id to the back of the line."""
    get_redis().lpush(QUEUE, str(scan_id))


def next_scan(worker: str, timeout: int = WAIT_SECONDS) -> uuid.UUID | None:
    """Wait up to `timeout` seconds for the oldest waiting scan, and MOVE it into this worker's
    in-progress list in the same step. None if the line stayed empty."""
    item = get_redis().blmove(QUEUE, in_progress(worker), timeout, "RIGHT", "LEFT")
    return uuid.UUID(item) if item else None


def finish_scan(worker: str, scan_id: uuid.UUID) -> None:
    """The scan is done (completed or failed): remove it from this worker's in-progress list."""
    get_redis().lrem(in_progress(worker), 1, str(scan_id))


def recover(worker: str) -> list[uuid.UUID]:
    """Put back any scans this worker had started but never finished (it crashed).

    They go to the FRONT of the line, so they are the next ones taken.
    """
    recovered = []
    while item := get_redis().lmove(in_progress(worker), QUEUE, "RIGHT", "RIGHT"):
        recovered.append(uuid.UUID(item))
    return recovered


def waiting() -> int:
    """How many scans are in the line right now."""
    return get_redis().llen(QUEUE)
