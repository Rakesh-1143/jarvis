"""Piece AG: localai (offline answers with Ollama). The HTTP calls are faked."""
import urllib.error

import pytest

from jarvis.actions import localai as la


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """Clean state, default settings, no real network."""
    la._state.update({"mode": None, "history": [], "status": None, "status_at": 0.0})
    s = dict(la.DEFAULTS)
    monkeypatch.setattr(la, "_settings", lambda: dict(s))

    def no_net(*a, **k):
        raise urllib.error.URLError("no network in tests")

    monkeypatch.setattr(la, "_get_json", no_net)
    monkeypatch.setattr(la, "_post_stream", no_net)
    yield s
    la._state.update({"mode": None, "history": [], "status": None, "status_at": 0.0})


def server(monkeypatch, models=("llama3.2:3b",)):
    calls = []

    def get_json(url, timeout):
        calls.append(url)
        return {"models": [{"name": m} for m in models]}

    monkeypatch.setattr(la, "_get_json", get_json)
    return calls


def stream(monkeypatch, pieces, error=None):
    sent = {}

    def post(url, body, timeout):
        sent.update(url=url, body=body)
        for p in pieces:
            yield {"message": {"role": "assistant", "content": p}, "done": False}
        if error:
            raise error
        yield {"message": {"role": "assistant", "content": ""}, "done": True}

    monkeypatch.setattr(la, "_post_stream", post)
    return sent


# ---------- status / available ----------

def test_not_available_when_server_down():
    assert la.available() is False
    st = la.status(force=True)
    assert st["server"] is False and st["model_ready"] is False


def test_available_when_model_pulled(monkeypatch):
    calls = server(monkeypatch)
    assert la.available() is True
    assert calls[0] == "http://localhost:11434/api/tags"


def test_not_available_when_model_missing(monkeypatch):
    server(monkeypatch, models=("mistral:latest",))
    st = la.status(force=True)
    assert st["server"] is True and st["model_ready"] is False
    assert la.available() is False


def test_model_without_tag_matches_latest(monkeypatch, fresh):
    fresh["model"] = "llama3.2"
    server(monkeypatch, models=("llama3.2:latest",))
    assert la.available() is True


def test_status_is_cached(monkeypatch):
    calls = server(monkeypatch)
    la.available()
    la.available()
    assert len(calls) == 1
    la.status(force=True)
    assert len(calls) == 2


# ---------- ask ----------

def test_ask_streams_sentences(monkeypatch):
    sent = stream(monkeypatch, ["Paris is the ", "capital of France. It is ", "known for the **Eiffel** Tower."])
    said = []
    answer = la.ask("what is the capital of france", on_sentence=said.append)
    assert said == ["Paris is the capital of France.", "It is known for the Eiffel Tower."]
    assert answer == "Paris is the capital of France. It is known for the Eiffel Tower."
    body = sent["body"]
    assert sent["url"].endswith("/api/chat")
    assert body["model"] == "llama3.2:3b" and body["stream"] is True
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1] == {"role": "user", "content": "what is the capital of france"}
    assert "tools" not in body


def test_ask_without_callback_returns_text(monkeypatch):
    stream(monkeypatch, ["Two plus two is four."])
    assert la.ask("two plus two") == "Two plus two is four."


def test_ask_cleans_markdown_and_links(monkeypatch):
    stream(monkeypatch, ["- **Step one**: see https://x.com now."])
    assert la.ask("how") == "Step one: see now."


def test_ask_keeps_history_for_follow_ups(monkeypatch):
    stream(monkeypatch, ["Paris."])
    la.ask("capital of france")
    sent = stream(monkeypatch, ["About two million."])
    la.ask("how many people live there")
    msgs = sent["body"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "capital of france" and msgs[2]["content"] == "Paris."


def test_history_is_trimmed(monkeypatch, fresh):
    fresh["history_turns"] = 1
    for q in ("a", "b", "c"):
        stream(monkeypatch, [q.upper() + "."])
        la.ask(q)
    assert [m["content"] for m in la._state["history"]] == ["c", "C."]
    la.clear_history()
    assert la._state["history"] == []


def test_ask_server_down_says_so():
    said = []
    msg = la.ask("hello", on_sentence=said.append)
    assert "not running" in msg
    assert said == [msg]


def test_ask_model_missing(monkeypatch):
    def post(url, body, timeout):
        raise urllib.error.HTTPError(url, 404, "model 'llama3.2:3b' not found", None, None)
        yield  # pragma: no cover

    monkeypatch.setattr(la, "_post_stream", post)
    assert "ollama pull llama3.2:3b" in la.ask("hi")


def test_ask_error_chunk(monkeypatch):
    monkeypatch.setattr(la, "_post_stream", lambda *a, **k: iter([{"error": "model 'x' not found"}]))
    assert "not downloaded" in la.ask("hi")


def test_ask_timeout(monkeypatch):
    stream(monkeypatch, [], error=TimeoutError("timed out"))
    assert "too long" in la.ask("hi")


def test_error_mid_answer_does_not_speak_twice(monkeypatch):
    stream(monkeypatch, ["First part. "], error=urllib.error.URLError("reset"))
    said = []
    la.ask("hi", on_sentence=said.append)
    assert said == ["First part."]


def test_ask_empty_text():
    said = []
    assert "What should" in la.ask("  ", on_sentence=said.append)
    assert said == ["What should I ask the local AI?"]


def test_ask_empty_answer(monkeypatch):
    stream(monkeypatch, [""])
    said = []
    assert la.ask("hi", on_sentence=said.append) == "The local AI gave no answer."
    assert said == ["The local AI gave no answer."]


def test_failed_ask_clears_status_cache(monkeypatch):
    server(monkeypatch)
    assert la.available()
    la.ask("hi")  # _post_stream still fails
    assert la._state["status"] is None


# ---------- mode / use_local ----------

def test_mode_default_from_config(fresh):
    assert la.get_mode() == "auto"
    fresh["mode"] = "local"
    assert la.get_mode() == "local"


def test_set_mode_rejects_bad_value():
    with pytest.raises(ValueError):
        la.set_mode("banana")


def test_use_local_rules(monkeypatch):
    server(monkeypatch)
    la.set_mode("auto")
    assert la.use_local(claude_ready=True) is False
    assert la.use_local(claude_ready=False) is True
    la.set_mode("cloud")
    assert la.use_local(claude_ready=False) is False
    la.set_mode("local")
    assert la.use_local(claude_ready=True) is True


def test_use_local_false_when_not_available():
    la.set_mode("local")
    assert la.use_local(claude_ready=False) is False


# ---------- handlers ----------

def test_ai_mode_local_ready(monkeypatch):
    server(monkeypatch)
    assert "use the local AI" in la.ai_mode({"mode": "local"})
    assert la.get_mode() == "local"


def test_ai_mode_local_server_down():
    assert "Ollama is not running" in la.ai_mode({"mode": "offline"})
    assert la.get_mode() == "local"


def test_ai_mode_local_model_missing(monkeypatch):
    server(monkeypatch, models=())
    assert "ollama pull" in la.ai_mode({"mode": "local"})


def test_ai_mode_cloud_and_auto():
    assert "cloud AI" in la.ai_mode({"mode": "claude"})
    assert la.get_mode() == "cloud"
    assert "auto mode" in la.ai_mode({"mode": "auto"})
    assert la.get_mode() == "auto"


def test_ai_mode_bad():
    assert "Say use local AI" in la.ai_mode({"mode": "x"})
    assert la._state["mode"] is None


def test_status_handler_messages(monkeypatch):
    assert "not running" in la.local_ai_status({})
    server(monkeypatch, models=())
    assert "not downloaded" in la.local_ai_status({})
    server(monkeypatch)
    assert la.local_ai_status({}) == "Local AI is ready with llama3.2:3b. AI mode is auto."


# ---------- catalog ----------

def test_catalog_matches_handlers():
    assert set(la.CATALOG) == set(la.HANDLERS) == {"ai_mode", "local_ai_status"}
    assert la.CATALOG["local_ai_status"].get("info") is True
    assert "info" not in la.CATALOG["ai_mode"]
    for spec in la.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)


def test_settings_reads_config(monkeypatch):
    monkeypatch.undo()  # real _settings
    import jarvis.config as c
    monkeypatch.setattr(c, "load_config", lambda: {"local_ai": {"model": "phi3", "url": "http://pc:1/",
                                                                "mode": "bad", "timeout": "x"}})
    s = la._settings()
    assert s["model"] == "phi3" and s["url"] == "http://pc:1" and s["mode"] == "auto"
    assert s["timeout"] == 60
