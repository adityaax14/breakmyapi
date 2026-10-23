"""Tests for jobs.py: order, the in-progress list, and recovery after a crash.
Uses a fake Redis, so no server is needed."""

import uuid

import pytest

import breakmyapi.jobs as jobs


class FakeRedis:
    """Just enough of Redis for jobs.py. Each list is a Python list: index 0 is the LEFT end."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def _list(self, name):
        return self.lists.setdefault(name, [])

    def lpush(self, name, value):
        self._list(name).insert(0, value)

    def _move(self, source, destination, where_from, where_to):
        items = self._list(source)
        if not items:
            return None
        value = items.pop() if where_from == "RIGHT" else items.pop(0)
        if where_to == "LEFT":
            self._list(destination).insert(0, value)
        else:
            self._list(destination).append(value)
        return value

    def lmove(self, source, destination, where_from, where_to):
        return self._move(source, destination, where_from, where_to)

    def blmove(self, source, destination, timeout, where_from, where_to):
        return self._move(source, destination, where_from, where_to)  # the real one would wait

    def lrem(self, name, count, value):
        self._list(name).remove(value)

    def llen(self, name):
        return len(self._list(name))


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jobs, "get_redis", lambda: fake)
    return fake


def test_scans_come_out_in_the_order_they_went_in():
    first, second = uuid.uuid4(), uuid.uuid4()
    jobs.enqueue_scan(first)
    jobs.enqueue_scan(second)
    assert jobs.next_scan("w1") == first
    assert jobs.next_scan("w1") == second


def test_empty_queue_gives_none():
    assert jobs.next_scan("w1", timeout=1) is None


def test_a_taken_scan_waits_in_progress_until_finished(fake_redis):
    scan = uuid.uuid4()
    jobs.enqueue_scan(scan)
    jobs.next_scan("w1")
    assert fake_redis.llen(jobs.in_progress("w1")) == 1  # still remembered while it runs
    jobs.finish_scan("w1", scan)
    assert fake_redis.llen(jobs.in_progress("w1")) == 0


def test_a_crashed_scan_is_recovered_and_runs_next():
    crashed, waiting_one = uuid.uuid4(), uuid.uuid4()
    jobs.enqueue_scan(crashed)
    jobs.next_scan("w1")             # the worker takes it ... and crashes (never calls finish_scan)
    jobs.enqueue_scan(waiting_one)   # meanwhile another scan joins the line

    assert jobs.recover("w1") == [crashed]
    assert jobs.next_scan("w1") == crashed  # the recovered scan goes first
    assert jobs.next_scan("w1") == waiting_one


def test_workers_do_not_recover_each_others_scans():
    scan = uuid.uuid4()
    jobs.enqueue_scan(scan)
    jobs.next_scan("w1")
    assert jobs.recover("w2") == []  # w2 must not steal a scan w1 may still be running
