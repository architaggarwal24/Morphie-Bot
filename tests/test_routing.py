import pytest

from morphie.routing import is_greeting


@pytest.mark.parametrize("text", ["hi", "Hello", "hey", "yo", "hii", "hi!", "  Hello.  ", "HEY!!"])
def test_greetings_are_recognised(text):
    assert is_greeting(text) is True


@pytest.mark.parametrize("text", [
    "hi there, can you help me plan a trip?",
    "history of rome",
    "hello world in python",
    "What's 20% of 500?",
    "",
    "   ",
])
def test_ordinary_messages_are_not_greetings(text):
    assert is_greeting(text) is False


@pytest.mark.parametrize("value", [None, 123, ["hi"], {"text": "hi"}])
def test_non_string_input_is_never_a_greeting(value):
    assert is_greeting(value) is False
