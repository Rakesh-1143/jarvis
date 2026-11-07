"""Tests for piece X: clipboard history. No real clipboard or keyboard is used."""
import json
import time

import pytest

from jarvis.actions import cliphistory as ch


@pytest.fixture(autouse=True)
def fake(monkeypatch, tmp_path):
    """Fake clipboard + keyboard, empty history, default settings."""
    state = {"clip": "", "pasted": 0, "excluded": False}
    monkeypatch.setattr(ch, "_read_clipboard", lambda: state["clip"])

    def write(text):
        state["clip"] = text

    def paste():
        state["pasted"] += 1

    monkeypatch.setattr(ch, "_write_clipboard", write)
    monkeypatch.setattr(ch, "_press_paste", paste)
    monkeypatch.setattr(ch, "_excluded", lambda: state["excluded"])
    monkeypatch.setattr(ch, "_cfg", {**ch.DEFAULTS, "file": str(tmp_path / "h.json")})
    ch.stop()
    ch._items.clear()
    ch._last_seen = None
    yield state
    ch.stop()
    ch._items.clear()


def copy(state, text):
    state["clip"] = text
    ch.poll_once()


def test_poll_keeps_newest_first_and_no_duplicates(fake):
    for t in ["one", "two", "three", "two"]:
        copy(fake, t)
    assert ch.items() == ["two", "three", "one"]


def test_same_clipboard_twice_is_added_once(fake):
    copy(fake, "hello")
    ch.poll_once()
    assert ch.items() == ["hello"]


def test_max_items(fake, monkeypatch):
    monkeypatch.setitem(ch._cfg, "max_items", 3)
    for i in range(6):
        copy(fake, f"note {i}")
    assert ch.items() == ["note 5", "note 4", "note 3"]


@pytest.mark.parametrize("text", ["Summer2024!", "aB3$kL9qZ", "P@ssw0rd", "x7Hq-92Lm",
                                  "sk-ant-api03-abcdefghijklmnop1234567890",
                                  "ghp_ABCDEFGHIJKLMNOPQRSTUV123456"])
def test_secrets_are_skipped(fake, text):
    copy(fake, text)
    assert ch.items() == []


@pytest.mark.parametrize("text", ["hello world", "Hello-World", "12345678", "file_name.txt",
                                  "https://example.com/Page?id=42", "me.name@Mail2.com",
                                  "C:\\Users\\Me\\Doc1.txt", "meeting at 5 PM", "short1A",
                                  "abc12345"])
def test_normal_text_is_kept(fake, text):
    copy(fake, text)
    assert ch.items() == [text]


def test_skip_secrets_can_be_turned_off(fake, monkeypatch):
    monkeypatch.setitem(ch._cfg, "skip_secrets", False)
    copy(fake, "Summer2024!")
    assert ch.items() == ["Summer2024!"]


def test_password_manager_private_copy_is_skipped(fake):
    fake["excluded"] = True
    copy(fake, "some private text")
    assert ch.items() == []


def test_too_long_or_empty_text_is_skipped(fake, monkeypatch):
    monkeypatch.setitem(ch._cfg, "max_chars", 10)
    copy(fake, "this is longer than ten")
    copy(fake, "   ")
    assert ch.items() == []


def test_list(fake):
    assert "haven't seen" in ch.clip_history({"action": "list"})
    for t in ["alpha", "beta", "gamma", "delta"]:
        copy(fake, t)
    r = ch.clip_history({"action": "list"})
    assert "1: delta" in r and "2: gamma" in r and "3: beta" in r
    assert "alpha" not in r and "4 items" in r


def test_list_shortens_long_items(fake):
    copy(fake, "word " * 50)
    r = ch.clip_history({"action": "list"})
    assert "..." in r and len(r) < 120


def test_paste_default_is_second_last(fake):
    copy(fake, "first copy")
    copy(fake, "second copy")
    r = ch.clip_history({"action": "paste"})
    assert r == "Pasted item 2."
    assert fake["clip"] == "first copy" and fake["pasted"] == 1
    # moved to the top, and the next poll does not add it again
    ch.poll_once()
    assert ch.items() == ["first copy", "second copy"]


@pytest.mark.parametrize("index", [3, "3", "3rd", "third", "item 3", "third one"])
def test_copy_by_index(fake, index):
    for t in ["a1 x", "b2 x", "c3 x", "d4 x"]:
        copy(fake, t)
    r = ch.clip_history({"action": "copy", "index": index})
    assert r.startswith("Copied item 3 again")
    assert fake["clip"] == "b2 x" and fake["pasted"] == 0


def test_second_last_words(fake):
    for t in ["old one", "new one"]:
        copy(fake, t)
    ch.clip_history({"action": "paste", "index": "second last"})
    assert fake["clip"] == "old one"


def test_paste_with_one_item_uses_it(fake):
    copy(fake, "only thing")
    assert ch.clip_history({"action": "paste"}) == "Pasted item 1."


def test_bad_index(fake):
    copy(fake, "x y")
    copy(fake, "y z")
    assert "only have 2" in ch.clip_history({"action": "paste", "index": 9})
    assert "Which item" in ch.clip_history({"action": "copy", "index": "banana"})
    assert "Which item" in ch.clip_history({"action": "copy", "index": 0})


def test_paste_failure_says_so(fake, monkeypatch):
    copy(fake, "a b")
    copy(fake, "c d")

    def boom():
        raise RuntimeError("no keyboard")

    monkeypatch.setattr(ch, "_press_paste", boom)
    r = ch.clip_history({"action": "paste"})
    assert "couldn't paste" in r and fake["clip"] == "a b"


def test_clear_needs_confirm(fake):
    copy(fake, "keep me")
    assert ch.needs_confirm({"action": "clear"})
    assert not ch.needs_confirm({"action": "list"})
    assert ch.risky_text({"action": "clear"}) == "clear the clipboard history"
    assert ch.risky_text({"action": "paste"}) is None
    r = ch.clip_history({"action": "clear"})
    assert "Are you sure" in r and ch.items() == ["keep me"]
    assert ch.clip_history({"action": "clear", "confirm": "yes"}).startswith("Are you sure")
    assert ch.clip_history({"action": "clear", "confirm": True}) == "Cleared the clipboard history."
    assert ch.items() == []


def test_not_saved_by_default(fake, tmp_path):
    copy(fake, "secret plan")
    assert not (tmp_path / "h.json").exists()


def test_save_and_load(fake, monkeypatch, tmp_path):
    monkeypatch.setitem(ch._cfg, "save", True)
    copy(fake, "saved note")
    f = tmp_path / "h.json"
    assert json.loads(f.read_text(encoding="utf-8")) == ["saved note"]
    ch._items.clear()
    ch._load(ch._cfg)
    assert ch.items() == ["saved note"]
    ch.clip_history({"action": "clear", "confirm": True})
    assert not f.exists()


def test_disabled(fake, monkeypatch):
    monkeypatch.setitem(ch._cfg, "enabled", False)
    assert "turned off" in ch.clip_history({"action": "list"})
    assert ch.start(dict(clipboard_history={"enabled": False})) is False
    assert not ch.is_running()


def test_start_thread_watches_clipboard(fake):
    cfg = {"clipboard_history": {"poll_seconds": 0.2, "file": ch._cfg["file"]}}
    assert ch.start(cfg) is True
    assert ch.start(cfg) is True  # second call does not start another thread
    fake["clip"] = "copied while running"
    for _ in range(30):
        if ch.items():
            break
        time.sleep(0.05)
    assert ch.items() == ["copied while running"]
    ch.stop()
    assert not ch.is_running()


def test_loop_survives_errors(fake, monkeypatch):
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise RuntimeError("clipboard busy")

    monkeypatch.setattr(ch, "_read_clipboard", bad)
    ch.start({"clipboard_history": {"poll_seconds": 0.2}})
    time.sleep(0.5)
    assert ch.is_running() and calls["n"] >= 2


def test_catalog_matches_handlers():
    assert set(ch.CATALOG) == set(ch.HANDLERS) == {"clip_history"}
    spec = ch.CATALOG["clip_history"]
    assert spec["required"] == ["action"]
    assert spec["properties"]["action"]["enum"] == ["list", "paste", "copy", "clear"]
    assert spec["info"] is False
