"""Tiny HTTP helpers using only the standard library."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

UA = "Jarvis-Assistant/0.1 (+https://github.com)"


def get(url: str, params: dict | None = None, timeout: float = 10, headers: dict | None = None) -> bytes:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url: str, params: dict | None = None, timeout: float = 10) -> dict:
    return json.loads(get(url, params, timeout))


def post_json(url: str, body: dict, timeout: float = 120, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA, **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())
