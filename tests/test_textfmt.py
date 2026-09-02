from stt.textfmt import apply_format


def test_none_or_empty_mode_is_a_passthrough():
    assert apply_format("Hello there.", None) == "Hello there."
    assert apply_format("Hello there.", "") == "Hello there."


def test_snake_case():
    assert apply_format("my user name", "snake") == "my_user_name"
    assert apply_format("Get the HTTP client.", "snake") == "get_the_http_client"


def test_camel_case():
    assert apply_format("my user name", "camel") == "myUserName"
    assert apply_format("Set retry count to 3.", "camel") == "setRetryCountTo3"


def test_raw_drops_punctuation_and_case_but_keeps_words():
    assert apply_format("Well, that's it!", "raw") == "well thats it"


def test_empty_after_stripping_punctuation():
    assert apply_format("...", "snake") == ""


def test_unknown_mode_is_left_alone():
    assert apply_format("leave me be", "kebab") == "leave me be"
