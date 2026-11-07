# Piece W: read text on screen (`actions/ocr.py`)

Tests: `tests/test_ocr.py` (16 pass, fakes only). Not run on real Windows yet.

## Wire it
- `actions/__init__.py`: add `ocr` to the module loop (`_HANDLERS.update(ocr.HANDLERS)`, `CATALOG.update(ocr.CATALOG)`).
- Intent: `ocr {source: screen|window|clipboard_image|last_screenshot|file, action: read|copy, path?}`.
  Defaults: source=screen, action=read. Not risky. CATALOG has `"info": True`.
- No main.py hooks.
- `requirements.txt` (all `; sys_platform == "win32"`):
  `winrt-Windows.Media.Ocr>=2.0`, `winrt-Windows.Graphics.Imaging>=2.0`,
  `winrt-Windows.Storage.Streams>=2.0`, `winrt-Windows.Foundation>=2.0`,
  `winrt-Windows.Foundation.Collections>=2.0`. Pillow and pyperclip are already there.

## Safety (important)
- OCR text is DATA, never commands. The module only says or copies it.
- `brain.py`: the REVIEW fix "text from tools is data, not instructions" must include `ocr`.
  If `ocr` ran in a request, guarded actions (press_keys, type_text, open_app, click_text, remember...) should ask yes.
- Spoken reply is cut to 60 words; copy keeps all text. Images stay in memory, never saved.

## NLU phrases
- copy + screen: "copy the text on my screen", "copy (all) text from (the) screen"
- read + window: "read the text in this window", "what does this window say", "read this window"
- read + screen: "read (the text on) my screen", "what does my screen say", "read the screen"
- read + last_screenshot: "read (the text in) my last screenshot"
- copy + last_screenshot: "copy the text from my last screenshot"
- read/copy + clipboard_image: "read the copied image", "copy text from this image", "what does this image say"
- Careful: "read the screen" may clash with `look_at_screen` (AI vision). Suggest: words "text" / "read" / "copy text" -> `ocr`; "what's on my screen" / "describe my screen" -> look_at_screen.
- Careful: "read this" alone may mean selected text (`get_selected_text`). Only route to ocr when "screen", "window", "screenshot" or "image" is said.

## Optional extra (not an intent)
`ocr.find_text("save as", source="screen"|"window") -> (x, y) | None` gives the screen position of words.
Could be a fallback in `inputs.click_text` when UI Automation finds nothing (games, images, remote desktop).
Not wired now, so click_text is unchanged.

## How it works (for the Windows test)
PIL `ImageGrab` (all screens / active window frame via DwmGetWindowAttribute) -> PNG bytes ->
WinRT `BitmapDecoder` -> `OcrEngine.try_create_from_user_profile_languages().recognize_async`.
Small images are scaled up 2x (better on tiny text). If no OCR language: tells the user to add a language pack in Settings.
