import io
import json

from stt import cleanup
from stt.cleanup import clean_text


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reply(content):
    return FakeResp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def test_clean_text_returns_the_models_output(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return _reply("I went to the store.")

    monkeypatch.setattr(cleanup.urllib.request, "urlopen", fake_urlopen)
    out = clean_text("um i went to the store like", "http://llm.test/v1", "test-model")
    assert out == "I went to the store."
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["body"]["model"] == "test-model"


def test_clean_text_fails_open_on_error(monkeypatch, caplog):
    def boom(*a, **k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(cleanup.urllib.request, "urlopen", boom)
    with caplog.at_level("WARNING"):
        assert clean_text("keep me exactly", "http://x/v1", "test-model") == "keep me exactly"
    assert "cleanup skipped" in caplog.text


def test_clean_text_passthrough_on_empty(monkeypatch):
    monkeypatch.setattr(cleanup.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert clean_text("   ", "http://x/v1", "test-model") == "   "


def test_clean_text_keeps_original_if_model_returns_blank(monkeypatch):
    monkeypatch.setattr(cleanup.urllib.request, "urlopen", lambda *a, **k: _reply("  "))
    assert clean_text("original", "http://x/v1", "test-model") == "original"
