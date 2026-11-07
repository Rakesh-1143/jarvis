# Wiring notes: piece M (browser.py)

Merge: `from .browser import CATALOG as CB, HANDLERS as HB`, then update catalog CATALOG and _HANDLERS.
Intents: `browser {action, text?}` (action), `page_text {read?}` (info). No risky intents. No main.py hooks.
No new requirements (uses pyautogui + pyperclip, already listed).

## NLU phrases -> intent + args
| Say | Intent | Args |
|---|---|---|
| "new tab", "open a new tab" | browser | {action: "new_tab"} |
| "close tab", "close this tab" | browser | {action: "close_tab"} |
| "reopen closed tab", "bring back that tab", "undo close tab" | browser | {action: "reopen_tab"} |
| "next tab", "switch tab" / "previous tab", "last tab" | browser | {action: "next_tab"} / {action: "previous_tab"} |
| "go back", "back" / "go forward" | browser | {action: "back"} / {action: "forward"} |
| "refresh", "reload the page" / "hard refresh" | browser | {action: "refresh"} / {action: "hard_refresh"} |
| "zoom in" / "zoom out" / "reset zoom", "normal size" | browser | {action: "zoom_in" / "zoom_out" / "zoom_reset"} |
| "bookmark this page", "bookmark this" | browser | {action: "bookmark"} |
| "find on page", "find price on this page", "search this page for price" | browser | {action: "find", text?: "price"} |
| "incognito window", "private window", "open incognito" | browser | {action: "incognito"} |
| "new window" (browser) | browser | {action: "new_window"} |
| "show history", "browser history" | browser | {action: "history"} |
| "show downloads", "open downloads page" | browser | {action: "downloads"} |
| "go to address bar" | browser | {action: "address_bar"} |
| "scroll down" / "scroll up" / "go to top" / "go to bottom" | browser | {action: "scroll_down" / "scroll_up" / "top" / "bottom"} |
| "full screen" | browser | {action: "fullscreen"} |
| "summarize this page", "what's this page about", "explain this page" | page_text | {} -> send to brain (info) |
| "read this page", "read this page out loud" | page_text | {read: true} (run directly, speak reply) |

Notes / conflicts to check:
- "go back", "zoom in/out", "scroll", "full screen", "new window" may clash with existing desktop/inputs/window rules. Suggest: match browser rules only with the words "tab", "page", "browser", "incognito", "private", "bookmark", or when it is clearly browser-only (reopen tab). Let generic "zoom in" etc. go to browser too unless another intent already owns it.
- "show downloads" may clash with piece O `recent_files`; "open my downloads folder" = open_folder, "downloads page" = browser.
- "summarize this page": core should call the brain with the user's text; the brain calls `page_text` (info) and answers. If no AI key, run `page_text {read: true}` instead.
- Safety: close_tab, new_tab, bookmark, incognito etc. are NOT sent if the window in front is clearly not a browser (avoids ctrl+W closing a Word doc). Scroll/zoom/back/find still work in any app.
- Firefox gets its own keys for incognito (ctrl+shift+P) and downloads (ctrl+shift+Y).
- page_text re-downloads the URL with urllib: pages behind a login or built only with JavaScript give little/no text. Clipboard is restored after copying the URL.
- Tests: `tests/test_browser.py` (12).
