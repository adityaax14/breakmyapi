"""The worker: a separate program that takes scans from the queue and runs them, one at a time.

Run it in its own terminal (Postgres and Redis running):
  uv run python -m breakmyapi.worker
To run two at once, give each a different name (each keeps its own in-progress list):
  $env:WORKER_NAME="worker-2"; uv run python -m breakmyapi.worker
Stop it with Ctrl+C.
"""

import os
import time
import traceback

from redis import RedisError

from breakmyapi.jobs import finish_scan, next_scan, recover, waiting
from breakmyapi.scan_runner import prepare_retry, run_scan


def main() -> None:
    name = os.getenv("WORKER_NAME", "worker-1")

    # Anything this worker started but never finished last time (it crashed) goes back in the line.
    for scan_id in recover(name):
        prepare_retry(scan_id)
        print(f"recovered unfinished scan {scan_id}", flush=True)

    print(f"{name} started, {waiting()} scan(s) waiting", flush=True)
    try:
        while True:
            try:
                scan_id = next_scan(name)
            except RedisError as e:
                # Redis restarted or had a hiccup: the jobs are still in the line, so wait and retry.
                print(f"queue problem ({type(e).__name__}), retrying in 2 s", flush=True)
                time.sleep(2)
                continue
            if scan_id is None:
                continue  # nothing arrived in the last few seconds: wait again

            print(f"running scan {scan_id}", flush=True)
            try:
                run_scan(scan_id)
            except Exception:
                # One broken scan must not stop the worker: log it and take the next one.
                traceback.print_exc()
            finally:
                finish_scan(name, scan_id)  # done (or failed): take it off our in-progress list
            print(f"finished scan {scan_id}", flush=True)
    except KeyboardInterrupt:
        print(f"{name} stopped", flush=True)


if __name__ == "__main__":
    main()
