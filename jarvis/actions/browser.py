"""Piece M: browser control. Intents: browser {action, text?}, page_text {read?} (info).

Works with the browser window that is in front (Chrome, Edge, Firefox, Brave, Opera, Vivaldi).
Uses pyautogui hotkeys and pyperclip (already in requirements). Page text uses urllib only.
"""
from __future__ import annotations

import html
import codecs
import re
import urllib.parse
import time
import urllib.request
from html.parser import HTMLParser

TIMEOUT = 8
MAX_BYTES = 2_000_000          # stop reading big pages after 2 MB
INFO_CHARS = 6000              # text sent to the AI
READ_CHARS = 600               # text spoken by "read this page"
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "browser")

# action -> (hotkey for Chrome/Edge, hotkey for Firefox or None = same), reply
KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...] | None, str]] = {
    "new_tab": (("ctrl", "t"), None, "New tab."),
    "close_tab": (("ctrl", "w"), None, "Tab closed."),
    "reopen_tab": (("ctrl", "shift", "t"), None, "Reopened the last tab."),
    "next_tab": (("ctrl", "tab"), None, "Next tab."),
    "previous_tab": (("ctrl", "shift", "tab"), None, "Previous tab."),
    "back": (("alt", "left"), None, "Going back."),
    "forward": (("alt", "right"), None, "Going forward."),
    "refresh": (("f5",), None, "Refreshed."),
    "hard_refresh": (("ctrl", "f5"), None, "Refreshed without cache."),
    "zoom_in": (("ctrl", "+"), None, "Zoomed in."),
    "zoom_out": (("ctrl", "-"), None, "Zoomed out."),
    "zoom_reset": (("ctrl", "0"), None, "Zoom reset."),
    "bookmark": (("ctrl", "d"), None, "Bookmark dialog open. Say 'press enter' to save it."),
    "find": (("ctrl", "f"), None, "Find bar open."),
    "incognito": (("ctrl", "shift", "n"), ("ctrl", "shift", "p"), "Private window opened."),
    "new_window": (("ctrl", "n"), None, "New window."),
    "history": (("ctrl", "h"), None, "History opened."),
    "downloads": (("ctrl", "j"), ("ctrl", "shift", "y"), "Downloads opened."),
    "address_bar": (("ctrl", "l"), None, "Address bar ready."),
    "home": (("alt", "home"), None, "Going to the home page."),
    "fullscreen": (("f11",), None, "Full screen toggled."),
    "scroll_down": (("pagedown",), None, ""),
    "scroll_up": (("pageup",), None, ""),
    "top": (("home",), None, ""),
    "bottom": (("end",), None, ""),
}
# Keys that could close or change things in a non-browser window: only send to a browser.
_BROWSER_ONLY = {"close_tab", "reopen_tab", "bookmark", "incognito", "history", "downloads", "new_tab",
                 "new_window", "address_bar", "home", "next_tab", "previous_tab", "hard_refresh"}


def _pg():
    import pyautogui
    return pyautogui


def active_title() -> str | None:
    """Title of the window in front, or None if it can't be read."""
    try:
        title = _pg().getActiveWindowTitle()
    except Exception:
        return None
    if title is None:
        return None
    return re.sub(r"[​-‏⁠﻿]", "", str(title))  # Edge puts a zero-width space in its name


def browser_kind(title: str | None) -> str | None:
    """'firefox', 'chromium' (Chrome/Edge/Brave/...), or None if the window is not a browser.
    Unknown title (None) counts as 'chromium' so commands still work when the title can't be read."""
    if title is None:
        return "chromium"
    t = title.lower()
    if "firefox" in t:
        return "firefox"
    if any(b in t for b in BROWSERS):
        return "chromium"
    return None


def browser(args: dict) -> str:
    action = str(args.get("action") or "").strip().lower().replace(" ", "_").replace("-", "_")
    action = {"new": "new_tab", "close": "close_tab", "reopen": "reopen_tab", "next": "next_tab",
              "previous": "previous_tab", "prev_tab": "previous_tab", "reload": "refresh",
              "private": "incognito", "search_page": "find", "find_on_page": "find"}.get(action, action)
    if action not in KEYS:
        return "I can't do that in the browser."
    title = active_title()
    kind = browser_kind(title)
    # Unknown title: we can't be sure it is a browser, so don't send tab/window keys to it.
    if (kind is None or title is None) and action in _BROWSER_ONLY:
        return "Please switch to your browser first."
    keys, firefox_keys, reply = KEYS[action]
    if kind == "firefox" and firefox_keys:
        keys = firefox_keys
    pg = _pg()
    pg.hotkey(*keys)
    text = str(args.get("text") or "").strip()
    if action == "find" and text:
        time.sleep(0.2)
        if text.isascii():
            pg.write(text, interval=0.01)
            pg.press("enter")
            return f"Searching the page for {text}."
        return "Find bar open. Type the word."
    return reply


# ---------- page text ----------

class _TextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "template", "iframe", "aside"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre",
             "blockquote", "td", "th", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(re.sub(r"\s+", " ", data))  # source line breaks are not real breaks


def html_to_text(page: str) -> tuple[str, str]:
    """(title, readable text) from HTML. Drops scripts, styles, menus; joins spaces."""
    p = _TextParser()
    try:
        p.feed(page)
        p.close()
    except Exception:
        pass
    lines = []
    for line in "".join(p.parts).splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return html.unescape(p.title).strip(), "\n".join(lines)


def current_url() -> str | None:
    """Copy the address bar (ctrl+L, ctrl+C, Esc) and give the clipboard back as it was."""
    import pyperclip
    pg = _pg()
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    url = None
    try:
        pyperclip.copy("")
        pg.hotkey("ctrl", "l")
        time.sleep(0.15)
        pg.hotkey("ctrl", "c")
        time.sleep(0.15)
        pg.press("esc")
        url = (pyperclip.paste() or "").strip()
    finally:
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass
    if not url:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I) and re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
        url = "https://" + url  # Chrome hides "https://" in the bar
    return url if re.match(r"^https?://\S+$", url, re.I) else None


def fetch_text(url: str) -> tuple[str, str]:
    """(title, text) of a web page. Raises ValueError for non-HTML pages."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) jarvis-assistant/1.0",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        raw = r.read(MAX_BYTES)
        charset = r.headers.get_content_charset() or "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError:  # bad charset header: don't fail, just use utf-8
        charset = "utf-8"
    if ctype and "html" not in ctype and "text/plain" not in ctype:
        raise ValueError(ctype.split(";")[0])
    page = raw.decode(charset, errors="replace")
    if "text/plain" in ctype:
        return "", re.sub(r"[ \t]+", " ", page).strip()
    return html_to_text(page)


_ONE_TIME = re.compile(r"(?:^|[_-])(?:token|code|key|sig|signature|auth|otp|reset|confirm|verify|unsubscribe|magic|"
                       r"login|session|password)(?:$|[_-])", re.I)


def _one_time_link(url: str) -> bool:
    """True for links that a second visit could use up or trigger (password reset, sign-in, unsubscribe...)."""
    parts = urllib.parse.urlsplit(url)
    names = [k for k, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    return any(_ONE_TIME.search(n) for n in names) or bool(_ONE_TIME.search(parts.path.replace("/", "-")))


def page_text(args: dict) -> str:
    """Text of the page open in the browser. read=True: short version for speaking."""
    if browser_kind(active_title()) is None:
        return "Please switch to your browser first."
    url = current_url()
    if not url:
        return "I couldn't get this page's address."
    if _one_time_link(url):
        return ("This looks like a sign-in or one-time link, so I won't load it again. "
                "Select the text and say 'read this' instead.")
    try:
        title, text = fetch_text(url)
    except ValueError as e:
        return f"This page is not a web page I can read ({e})."
    except Exception:
        return "I couldn't load this page. It may need a login."
    if not text:
        return "This page has no text I can read. It may need a login or JavaScript."
    if args.get("read"):
        short = text[:READ_CHARS]
        if len(text) > READ_CHARS:
            short = short.rsplit(" ", 1)[0] + "..."
        return (f"{title}. " if title else "") + short
    more = "\n[text cut]" if len(text) > INFO_CHARS else ""
    shown = urllib.parse.urlsplit(url)._replace(query="", fragment="").geturl()  # the query can hold tokens
    return f"Page title: {title or '(none)'}\nURL: {shown}\n\n{text[:INFO_CHARS]}{more}"


CATALOG: dict[str, dict] = {
    "browser": {"description": "Control the web browser in front with hotkeys: tabs, back/forward, refresh, zoom, "
                               "bookmark, find on page (optional text), private window, history, downloads, scroll.",
                "properties": {"action": {"type": "string", "enum": sorted(KEYS)},
                               "text": {"type": "string", "description": "For find: the word to search on the page."}},
                "required": ["action"]},
    "page_text": {"description": "Get the text of the web page open in the browser (to summarize, explain or answer "
                                 "questions about it). read=true gives a short start of the page for reading aloud.",
                  "properties": {"read": {"type": "boolean"}}, "required": [], "info": True},
}
HANDLERS = {"browser": browser, "page_text": page_text}
