import traceback
import uuid
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy import update
from sqlalchemy.orm import Session

from breakmyapi.agent.graph import build_graph
from breakmyapi.agent.state import initial_state
from breakmyapi.config import get_settings
from breakmyapi.db import SessionLocal
from breakmyapi.models import Scan, ScanEvent
from breakmyapi.targets import TargetError, check_target

MAX_TESTS = 100  # one scan never plans more than this many tests (a budget, like a page-size limit)


def log(session: Session, scan: Scan, message: str) -> None:
    """Write one line in the scan's diary and save it at once, so the live stream can see it."""
    session.add(ScanEvent(scan_id=scan.id, message=message))
    session.commit()  # also saves any change to the scan itself, such as its status


def change_status(session: Session, scan_id: uuid.UUID, only_if: set[str], new_status: str) -> bool:
    """Change a scan's status, but ONLY if it is currently one of `only_if`. Returns True if it changed.

    The check and the change are ONE SQL statement:
        UPDATE scans SET status = 'cancelled' WHERE id = ... AND status IN ('queued', 'running')
    so two programs (the API and the worker) can never both "win": the database applies them
    one after the other, and the second one finds the status already changed and matches nothing.
    """
    result = session.execute(
        update(Scan).where(Scan.id == scan_id, Scan.status.in_(only_if)).values(status=new_status)
    )
    return result.rowcount == 1


class Cancelled(Exception):
    """The user pressed Cancel while this scan was running."""


def stop_if_cancelled(session: Session, scan: Scan) -> None:
    """Read the scan's status again from the database. If the user cancelled it, stop here."""
    session.refresh(scan)  # our copy is old: the API may have changed the status since we loaded it
    if scan.status == "cancelled":
        raise Cancelled


def prepare_retry(scan_id: uuid.UUID) -> None:
    """A worker crashed in the middle of this scan: set it back to "queued" so it can run again."""
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        if scan is not None and change_status(session, scan_id, {"running"}, "queued"):
            log(session, scan, "the worker stopped during this scan; it will run again")


@contextmanager
def checkpointer():
    """LangGraph's Postgres saver: stores the agent's notebook after every node.

    It talks to Postgres with plain psycopg, which wants "postgresql://", not SQLAlchemy's
    "postgresql+psycopg://". (Tests replace this function with an in-memory saver.)
    """
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()  # creates its tables the first time; does nothing afterwards
        yield saver


def describe(node: str, changes: dict) -> str | None:
    """One diary line for what a node just did (None = nothing worth showing)."""
    if node == "read":
        return f"read the spec: {len(changes['endpoints'])} endpoints"
    if node == "retrieve":
        found = {check: chunks for check, chunks in changes["guidance"].items() if chunks}
        total = sum(len(chunks) for chunks in found.values())
        return f"found {total} OWASP library sections for {len(found)} check types"
    if node == "plan":
        return f"planned {len(changes['plan'])} tests"
    if node == "approve":
        if changes["approval"] == "approved":
            return "approved: tests that change data will run"
        if changes["approval"] == "rejected":
            skipped = sum(r["outcome"] == "skipped" for r in changes["results"])
            return f"skipped {skipped} tests that change data, as you chose"
        return "no tests change data: no approval needed"
    if node == "execute" and "results" in changes:
        r = changes["results"][-1]
        mark = {"pass": "PASS", "fail": "FAIL", "needs_review": "REVIEW", "error": "ERROR"}.get(r["outcome"], "")
        prefix = f"[{mark}] " if mark else ""
        return f"{prefix}{r['check']} on {r['method']} {r['path']}: {r['note']}"
    if node == "report":
        return f"report written: {changes['report']}"
    return None


def run_agent(session: Session, scan: Scan) -> dict | None:
    """Run (or resume) the agent graph for this scan, writing the diary and checking Cancel between nodes.

    Returns None when the graph finished, or the QUESTION when it paused to ask the user
    (an interrupt in the approve node), e.g. {"tests": [...the tests that change data...]}.
    """
    # thread_id = which saved run this is. Using the scan id means a re-run finds its own checkpoint.
    # recursion_limit = the most steps one run may take. LangGraph's default is 10,007; ours is set
    # to what a real scan can need (each test takes 2 steps, execute + judge, plus a few for read,
    # retrieve, plan and report), so a bug that makes the loop never end is stopped quickly.
    config = {"configurable": {"thread_id": str(scan.id)}, "recursion_limit": 2 * MAX_TESTS + 10}

    with checkpointer() as saver:
        graph = build_graph(saver)
        saved = graph.get_state(config)
        if saved.interrupts:
            # The run is paused at a question. The user's answer is on the scan row (the API put it there).
            if scan.approval is None:
                return saved.interrupts[0].value  # no answer yet: still waiting
            log(session, scan, f"continuing with your answer: {scan.approval}")
            start = Command(resume=scan.approval)  # "resume the paused run; interrupt() returns this"
        elif saved.next:  # a checkpoint exists, with steps still to do: a worker crashed mid-run
            log(session, scan, f"resuming from the last saved step (next: {', '.join(saved.next)})")
            start = None  # None = "continue the saved run" instead of "start a new one"
        else:
            start = initial_state(scan.spec, scan.framework, scan.target_url, scan.test_token)

        question = None
        # stream(..., "updates") runs the graph and hands us {node name: what it changed} after each node.
        for update in graph.stream(start, config, stream_mode="updates"):
            if "__interrupt__" in update:
                # Not a node: LangGraph telling us the graph PAUSED. The stream ends right after this.
                question = update["__interrupt__"][0].value
                continue
            for node, changes in update.items():
                if node == "plan" and len(changes["plan"]) > MAX_TESTS:
                    raise ValueError(f"the spec needs {len(changes['plan'])} tests; the limit is {MAX_TESTS}")
                line = describe(node, changes or {})
                if line:
                    log(session, scan, line)
            stop_if_cancelled(session, scan)  # between nodes: Cancel takes effect at the next step

        if question is None:
            # Finished: copy the report out of the agent's memory (checkpoints) into the scan row,
            # where the API and UI read it. Checkpoints are the agent's working memory; the report
            # is the user's result and must outlive them.
            final = graph.get_state(config).values
            scan.report = {"summary": final["report"], "sections": final["sections"]}
        return question


def run_scan(scan_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        scan = session.get(Scan, scan_id)
        # Only start it if it is still waiting. A scan cancelled while in the queue stops here.
        if scan is None or not change_status(session, scan_id, {"queued"}, "running"):
            session.commit()
            return
        # A scan that already has an answer is coming back after the approval pause.
        log(session, scan, "scan resumed" if scan.approval else "scan started")

        try:
            # Check again here, not only in the API: the allowlist may have changed since the scan
            # was queued, and a scan could reach the queue some other way. (Defense in depth.)
            check_target(scan.target_url, session, scan.user_id)

            question = run_agent(session, scan)
            if question is not None:
                # Paused for the user. Save the question for the UI, and free this worker: we do NOT
                # sit here waiting (the answer could take seconds or days). The API re-queues the
                # scan when the user answers, and any worker then resumes it from the checkpoint.
                scan.approval_request = question
                scan.approval = None
                if change_status(session, scan_id, {"running"}, "waiting_approval"):
                    n = len(question["tests"])
                    log(session, scan, f"waiting for your approval: {n} tests could change data on your API")
                session.commit()
                return

            # "completed" only if nobody cancelled it during the last step.
            if change_status(session, scan_id, {"running"}, "completed"):
                log(session, scan, "scan completed")
            session.commit()
        except Cancelled:
            print(f"scan {scan_id} was cancelled; stopped", flush=True)
        except TargetError as e:
            # Not a crash, a refusal: say why in the diary, and send nothing to the target.
            if change_status(session, scan_id, {"running"}, "failed"):
                log(session, scan, f"refused: {e}")
            session.commit()
        except Exception:
            traceback.print_exc()
            session.rollback()
            if change_status(session, scan_id, {"running"}, "failed"):
                log(session, scan, "scan failed")
            session.commit()
