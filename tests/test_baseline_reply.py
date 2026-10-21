"""Tests for parse_reply in baselines/single_prompt.py: reading the model's answer safely."""

from breakmyapi.baselines.single_prompt import parse_reply
from breakmyapi.checks import FIRST_FOUR
from breakmyapi.spec.parser import Endpoint

EP = Endpoint("GET", "/notes/{note_id}", has_path_id=True, requires_auth=True, accepts_body=False, is_admin=False)


def ids(guesses):
    return [g.check_id for g in guesses]


def test_valid_reply_becomes_guesses():
    reply = '{"vulnerabilities": [{"check_id": "missing_auth", "reason": "r"}]}'
    guesses = parse_reply(reply, EP, FIRST_FOUR)
    assert ids(guesses) == ["missing_auth"]
    assert guesses[0].path == "/notes/{note_id}"  # the endpoint is filled in by us, not the model


def test_words_around_the_json_are_ignored():
    reply = 'Sure! {"vulnerabilities": [{"check_id": "missing_auth", "reason": "r"}]} Hope that helps.'
    assert ids(parse_reply(reply, EP, FIRST_FOUR)) == ["missing_auth"]


def test_empty_list_is_a_real_answer():
    assert parse_reply('{"vulnerabilities": []}', EP, FIRST_FOUR) == []


def test_made_up_check_ids_are_dropped():
    reply = '{"vulnerabilities": [{"check_id": "something_invented", "reason": "r"}]}'
    assert parse_reply(reply, EP, FIRST_FOUR) == []


def test_duplicates_are_removed():
    reply = '{"vulnerabilities": [{"check_id": "missing_auth"}, {"check_id": "missing_auth"}]}'
    assert ids(parse_reply(reply, EP, FIRST_FOUR)) == ["missing_auth"]


def test_broken_replies_return_none():
    assert parse_reply('{"vulnerabilities": [ {"check_id": ', EP, FIRST_FOUR) is None
    assert parse_reply("I think it is fine.", EP, FIRST_FOUR) is None
    assert parse_reply('{"something_else": 1}', EP, FIRST_FOUR) is None
