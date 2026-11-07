"""Web search in the default browser."""
from __future__ import annotations

import urllib.parse
import webbrowser

SEARCH_URL = "https://www.google.com/search?q={query}"


def search(query: str) -> str:
    query = query.strip()
    if not query:
        return "What should I search for?"
    url = SEARCH_URL.replace("{query}", urllib.parse.quote_plus(query))
    webbrowser.open(url)
    return f"Searching for {query}."
