"""Turns, Stop and rewind - the same behaviour from the in-memory history (local) and the D1 one (Workers)."""

import pytest

from fake_d1 import make_d1
from morphie.d1 import D1ConversationHistory
from morphie.history import ConversationHistory


@pytest.fixture(params=["memory", "d1"])
def history(request):
    if request.param == "memory":
        return ConversationHistory(max_messages=6)
    return D1ConversationHistory(make_d1(), max_messages=6, sweep_probability=0)


def test_a_turn_is_written_together_and_the_transcript_matches_what_the_model_sees(history):
    ids = history.append_turn("u", "t1", "hi", "hello!", meta={"sources": [{"document": "a.txt"}]})
    assert ids is not None and ids[0] < ids[1]
    assert history.get("u") == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello!"}]
    transcript = history.transcript("u")
    assert [(m["id"], m["role"], m["content"]) for m in transcript] == [(ids[0], "user", "hi"), (ids[1], "assistant", "hello!")]
    assert transcript[1]["meta"] == {"sources": [{"document": "a.txt"}]}


def test_stop_drops_a_finished_turn_and_blocks_one_that_is_still_finishing(history):
    history.append_turn("u", "t1", "q1", "a1")
    history.append_turn("u", "t2", "q2", "a2")
    history.cancel_turn("u", "t2")                        # Stop after it was written
    assert [m["content"] for m in history.get("u")] == ["q1", "a1"]
    history.cancel_turn("u", "t3")                        # Stop before it was written...
    assert history.append_turn("u", "t3", "q3", "a3") is None   # ...so it never is
    assert [m["content"] for m in history.get("u")] == ["q1", "a1"]
    assert history.is_cancelled("u", "t3") and not history.is_cancelled("u", "t1")


def test_rewind_forgets_a_message_and_everything_after_it(history):
    history.append_turn("u", "t1", "q1", "a1")
    second = history.append_turn("u", "t2", "q2", "a2")
    history.append_turn("u", "t3", "q3", "a3")
    removed = history.rewind("u", second[0])
    assert removed == 4
    assert [m["content"] for m in history.get("u")] == ["q1", "a1"]


def test_users_never_see_or_rewind_each_other(history):
    history.append_turn("a", "t1", "mine", "ok")
    other = history.append_turn("b", "t1", "theirs", "ok")
    history.rewind("a", 0)
    history.cancel_turn("a", "t1")
    assert [m["content"] for m in history.get("b")] == ["theirs", "ok"]
    assert history.transcript("b")[0]["id"] == other[0]


def test_the_window_stays_bounded(history):
    for i in range(10):
        history.append_turn("u", f"t{i}", f"q{i}", f"a{i}")
    assert len(history.get("u")) == 6 and history.get("u")[-1]["content"] == "a9"


def test_a_one_message_window_still_reports_both_ids():
    for history in (ConversationHistory(max_messages=1), D1ConversationHistory(make_d1(), max_messages=1, sweep_probability=0)):
        ids = history.append_turn("u", "t1", "q", "a")
        assert ids is not None and ids[0] < ids[1]
        assert [m["content"] for m in history.get("u")] == ["a"]
