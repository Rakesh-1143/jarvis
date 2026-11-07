"""Piece M: browser control. pyautogui, clipboard and internet are mocked."""
import io
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import browser as br  # noqa: E402

HTML = """<html><head><title>Cats &amp; Dogs</title><style>.x{color:red}</style>
<script>var a = 'hidden';</script></head><body><nav>Menu Home About</nav>
<h1>Pets</h1><p>Cats   are
 small.</p><p>Dogs are loyal.<br>Both are nice.</p><footer>Copyright</footer></body></html>"""


def fake_pg(title="Google - Google Chrome"):
    pg = mock.MagicMock()
    pg.getActiveWindowTitle.return_value = title
    return pg


class FakeClip:
    def __init__(self, url, old="old clip"):
        self.value, self.url = old, url

    def paste(self):
        return self.value

    def copy(self, v):
        self.value = v


def run_with(pg, fn, args, clip=None):
    mods = {"pyautogui": pg}
    if clip is not None:
        pc = types.ModuleType("pyperclip")
        pc.paste, pc.copy = clip.paste, clip.copy
        mods["pyperclip"] = pc

        def hotkey(*keys):
            if keys == ("ctrl", "c"):
                clip.value = clip.url
        pg.hotkey.side_effect = hotkey
    with mock.patch.dict(sys.modules, mods), mock.patch.object(br.time, "sleep"):
        return fn(args)


def test_catalog_matches_handlers():
    assert set(br.CATALOG) == set(br.HANDLERS)
    assert br.CATALOG["page_text"].get("info") is True
    assert set(br.CATALOG["browser"]["properties"]["action"]["enum"]) == set(br.KEYS)


def test_tab_hotkeys():
    for action, keys in [("new_tab", ("ctrl", "t")), ("close_tab", ("ctrl", "w")),
                         ("reopen_tab", ("ctrl", "shift", "t")), ("back", ("alt", "left")),
                         ("zoom_in", ("ctrl", "+")), ("refresh", ("f5",))]:
        pg = fake_pg()
        reply = run_with(pg, br.browser, {"action": action})
        pg.hotkey.assert_called_once_with(*keys)
        assert reply


def test_aliases_and_spaces():
    pg = fake_pg()
    run_with(pg, br.browser, {"action": "next tab"})
    pg.hotkey.assert_called_once_with("ctrl", "tab")
    pg = fake_pg()
    run_with(pg, br.browser, {"action": "reload"})
    pg.hotkey.assert_called_once_with("f5")


def test_unknown_action():
    pg = fake_pg()
    assert "can't" in run_with(pg, br.browser, {"action": "fly"})
    pg.hotkey.assert_not_called()


def test_incognito_firefox_vs_edge():
    pg = fake_pg("New Tab — Mozilla Firefox")
    run_with(pg, br.browser, {"action": "incognito"})
    pg.hotkey.assert_called_once_with("ctrl", "shift", "p")
    pg = fake_pg("Bing and 2 more pages - Personal - Microsoft​ Edge")
    run_with(pg, br.browser, {"action": "incognito"})
    pg.hotkey.assert_called_once_with("ctrl", "shift", "n")


def test_close_tab_blocked_outside_browser():
    pg = fake_pg("Document1 - Word")
    assert "switch to your browser" in run_with(pg, br.browser, {"action": "close_tab"})
    pg.hotkey.assert_not_called()


def test_unknown_title_only_safe_keys():
    pg = fake_pg(None)
    assert "switch to your browser" in run_with(pg, br.browser, {"action": "new_tab"})  # could hit another app
    pg.hotkey.assert_not_called()
    run_with(pg, br.browser, {"action": "back"})
    pg.hotkey.assert_called_once_with("alt", "left")


def test_one_time_links_are_not_loaded_again():
    assert br._one_time_link("https://site.com/reset?token=abc")
    assert br._one_time_link("https://mail.com/unsubscribe?id=1")
    assert not br._one_time_link("https://en.wikipedia.org/wiki/Python")


def test_find_with_text():
    pg = fake_pg()
    reply = run_with(pg, br.browser, {"action": "find", "text": "price"})
    pg.hotkey.assert_called_once_with("ctrl", "f")
    pg.write.assert_called_once()
    assert pg.write.call_args[0][0] == "price"
    assert "price" in reply


def test_html_to_text():
    title, text = br.html_to_text(HTML)
    assert title == "Cats & Dogs"
    assert "Cats are small." in text and "Both are nice." in text
    assert "hidden" not in text and "color" not in text and "Menu" not in text and "Copyright" not in text


class FakeResp(io.BytesIO):
    def __init__(self, body, ctype="text/html; charset=utf-8"):
        super().__init__(body.encode())
        from email.message import Message
        self.headers = Message()
        self.headers["Content-Type"] = ctype

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_page_text_info_and_clipboard_restored():
    pg, clip = fake_pg(), FakeClip("https://example.com/pets")
    with mock.patch.object(br.urllib.request, "urlopen", return_value=FakeResp(HTML)) as uo:
        out = run_with(pg, br.page_text, {}, clip)
    assert uo.call_args[0][0].full_url == "https://example.com/pets"
    assert "Page title: Cats & Dogs" in out and "Dogs are loyal." in out
    assert clip.value == "old clip"
    pg.press.assert_called_with("esc")


def test_page_text_read_is_short():
    body = "<title>Long</title><p>" + "word " * 1000 + "</p>"
    pg, clip = fake_pg(), FakeClip("example.com/long")
    with mock.patch.object(br.urllib.request, "urlopen", return_value=FakeResp(body)) as uo:
        out = run_with(pg, br.page_text, {"read": True}, clip)
    assert uo.call_args[0][0].full_url == "https://example.com/long"
    assert out.startswith("Long. ") and out.endswith("...") and len(out) < br.READ_CHARS + 20


def test_page_text_errors():
    pg, clip = fake_pg(), FakeClip("chrome://settings")
    assert "address" in run_with(pg, br.page_text, {}, clip)
    pg, clip = fake_pg(), FakeClip("https://x.com/a.pdf")
    with mock.patch.object(br.urllib.request, "urlopen", return_value=FakeResp("%PDF", "application/pdf")):
        assert "application/pdf" in run_with(pg, br.page_text, {}, clip)
    pg, clip = fake_pg(), FakeClip("https://x.com")
    with mock.patch.object(br.urllib.request, "urlopen", side_effect=OSError("down")):
        assert "couldn't load" in run_with(pg, br.page_text, {}, clip)
    assert "switch" in run_with(fake_pg("Notepad"), br.page_text, {})
