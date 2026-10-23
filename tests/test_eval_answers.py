"""Tests for rag/eval_answers.py: reading the judge's reply, and spotting refusals."""

from breakmyapi.rag.eval_answers import is_refusal, parse_claims


def test_judge_reply_becomes_claims():
    reply = 'Here: {"claims": [{"claim": "a", "supported": true}, {"claim": "b", "supported": false}]}'
    assert parse_claims(reply) == [{"claim": "a", "supported": True}, {"claim": "b", "supported": False}]


def test_claims_without_a_true_or_false_verdict_are_dropped():
    reply = '{"claims": [{"claim": "a", "supported": "maybe"}, {"claim": "b", "supported": true}]}'
    assert parse_claims(reply) == [{"claim": "b", "supported": True}]


def test_unusable_judge_replies_return_none():
    assert parse_claims("no json here") is None
    assert parse_claims('{"claims": "not a list"}') is None


def test_refusal_is_recognised_with_or_without_quotes_and_full_stop():
    assert is_refusal("The library does not cover this.")
    assert is_refusal('"The library does not cover this"')
    assert not is_refusal("Use an allowlist of fields [1].")
