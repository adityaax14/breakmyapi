"""Tests for evaluation/score.py: hits, false alarms, misses, precision and recall."""

from breakmyapi.evaluation.score import expected_findings, load_bugs, score

A = ("object_level_access", "GET /notes/{note_id}")
B = ("missing_auth", "GET /notes")
C = ("mass_assignment", "PATCH /users/me")


def test_perfect_scanner():
    s = score(reported={A, B}, expected={A, B})
    assert s.hits == {A, B}
    assert s.precision == 1.0
    assert s.recall == 1.0


def test_one_right_and_one_wrong():
    s = score(reported={A, C}, expected={A, B})
    assert s.hits == {A}
    assert s.false_alarms == {C}
    assert s.missed == {B}
    assert s.precision == 0.5
    assert s.recall == 0.5


def test_precision_is_undefined_when_nothing_is_reported():
    assert score(reported=set(), expected={A}).precision is None


def test_recall_is_undefined_when_there_are_no_real_bugs():
    assert score(reported={A}, expected=set()).recall is None


def test_answer_key_with_no_flags_expects_nothing():
    assert expected_findings(load_bugs(), set()) == set()


def test_answer_key_for_bola_lists_three_endpoints():
    expected = expected_findings(load_bugs(), {"bola"})
    assert len(expected) == 3
    assert all(check == "object_level_access" for check, _ in expected)
