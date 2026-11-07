"""Piece J: network info. Intent: network {what: online|ip|wifi|speed|ping, host?}.

No extra packages. Uses urllib, socket and Windows `netsh` / `ping`.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
import urllib.request

TIMEOUT = 5
ONLINE_URLS = ["http://www.msftconnecttest.com/connecttest.txt", "https://www.google.com/generate_204",
               "https://1.1.1.1"]
PUBLIC_IP_URL = "https://api.ipify.org"
SPEED_URLS = ["https://speed.cloudflare.com/__down?bytes=10000000",
              "http://speedtest.tele2.net/10MB.zip"]
SPEED_MAX_SECONDS = 15
HOSTS = {"google": "google.com", "youtube": "youtube.com", "microsoft": "microsoft.com",
         "cloudflare": "1.1.1.1", "router": "", "gateway": ""}
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no black cmd box


def _run(cmd: list[str], timeout: float = 15) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                         creationflags=_NO_WINDOW, errors="replace")
    return (out.stdout or "") + (out.stderr or "")


def _get(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def is_online() -> bool:
    for url in ONLINE_URLS:
        try:
            _get(url, timeout=3)
            return True
        except Exception:
            continue
    return False


def local_ip() -> str | None:
    """IP of this laptop on the local network. No packet is sent (UDP connect only picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return None if ip.startswith("0.") else ip
    except OSError:
        return None
    finally:
        s.close()


def public_ip() -> str | None:
    try:
        ip = _get(PUBLIC_IP_URL).decode().strip()
        return ip if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", ip) else None
    except Exception:
        return None


def wifi_info() -> dict:
    """{'ssid', 'signal', 'state'} from `netsh wlan show interfaces` (Windows)."""
    try:
        text = _run(["netsh", "wlan", "show", "interfaces"])
    except Exception:
        return {}
    info: dict = {}
    for line in text.splitlines():
        k, sep, v = line.partition(":")
        if not sep:
            continue
        k, v = k.strip().lower(), v.strip()
        if k == "ssid":
            info["ssid"] = v
        elif k == "signal":
            info["signal"] = v.rstrip("%").strip()
        elif k == "state":
            info["state"] = v.lower()
        elif k in ("receive rate (mbps)", "transmit rate (mbps)"):
            info.setdefault("rate", v)
    return info


def speed_test(max_seconds: float = SPEED_MAX_SECONDS) -> float | None:
    """Download a test file, return Mbps. None if it fails."""
    for url in SPEED_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jarvis-assistant/1.0"})
            got = 0
            start = time.perf_counter()
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
                    if time.perf_counter() - start > max_seconds:
                        break
            secs = time.perf_counter() - start
            if got > 100_000 and secs > 0:
                return got * 8 / secs / 1_000_000
        except Exception:
            continue
    return None


def _gateway() -> str | None:
    try:
        text = _run(["ipconfig"] if sys.platform == "win32" else ["ip", "route"])
    except Exception:
        return None
    m = re.search(r"Default Gateway[ .]*:\s*(\d+\.\d+\.\d+\.\d+)", text) or re.search(r"default via (\S+)", text)
    return m.group(1) if m else None


def ping(host: str = "google.com", count: int = 4) -> tuple[int | None, int, int]:
    """Return (average ms or None, replies, sent)."""
    flag = "-n" if sys.platform == "win32" else "-c"
    host = str(host or "").strip()
    if not host or host.startswith("-") or not re.fullmatch(r"[\w.:-]+", host):
        return None, 0, count  # a host starting with "-" would be read as a ping option
    try:
        text = _run(["ping", flag, str(count), host], timeout=count * 3 + 5)
    except Exception:
        return None, 0, count
    times = [float(x) for x in re.findall(r"time[=<]\s*([\d.]+)\s*ms", text, re.I)]
    avg = re.search(r"Average\s*=\s*(\d+)\s*ms", text) or re.search(r"=\s*[\d.]+/([\d.]+)/", text)
    ms = round(float(avg.group(1))) if avg else (round(sum(times) / len(times)) if times else None)
    return ms, len(times), count


def _host_for(name: str) -> str:
    n = re.sub(r"^(?:the|my)\s+", "", str(name or "").strip().lower())
    if not n:
        return "google.com"
    if n in HOSTS:
        return HOSTS[n] or (_gateway() or "")
    if re.fullmatch(r"[a-z0-9-]+", n):
        return n + ".com"
    return n


def network(args: dict) -> str:
    what = str(args.get("what") or "online").strip().lower()

    if what == "online":
        if is_online():
            return "Yes, you're online."
        return "No, you're offline. I can't reach the internet."

    if what == "ip":
        lan, pub = local_ip(), public_ip()
        if not lan and not pub:
            return "I couldn't find your IP address. You may be offline."
        parts = []
        if lan:
            parts.append(f"Your local IP is {lan}.")
        parts.append(f"Your public IP is {pub}." if pub else "I couldn't get your public IP.")
        return " ".join(parts)

    if what == "wifi":
        if sys.platform != "win32":
            return "Wi-Fi name only works on Windows."
        w = wifi_info()
        if not w.get("ssid") or w.get("state") not in (None, "connected"):
            return "You're not connected to Wi-Fi."
        out = f"You're on Wi-Fi {w['ssid']}"
        if w.get("signal"):
            out += f", signal {w['signal']} percent"
        return out + "."

    if what == "speed":
        mbps = speed_test()
        if mbps is None:
            return "I couldn't run the speed test. Check the internet connection."
        word = "fast" if mbps >= 50 else "okay" if mbps >= 10 else "slow"
        return f"Your download speed is about {mbps:.0f} megabits per second. That's {word}." if mbps >= 1 else \
            f"Your download speed is about {mbps:.1f} megabits per second. That's slow."

    if what == "ping":
        name = str(args.get("host") or "google")
        host = _host_for(name)
        if not host:
            return "I couldn't find your router's address."
        ms, ok, sent = ping(host)
        label = name.strip() or host
        if ok == 0:
            return f"No reply from {label}."
        loss = f" {sent - ok} of {sent} pings were lost." if ok < sent else ""
        return f"{label.title()} replied in {ms} milliseconds.{loss}"

    return "I can check if you're online, your IP, Wi-Fi name, internet speed, or ping a site."


# ---------------------------------------------------------------- wiring
CATALOG: dict[str, dict] = {
    "network": {"description": "Network checks: are we online, local and public IP, current Wi-Fi name and signal, "
                               "internet download speed (takes up to 15 s), or ping a site/router.",
                "properties": {"what": {"type": "string", "enum": ["online", "ip", "wifi", "speed", "ping"]},
                               "host": {"type": "string", "description": "For ping: site or 'router', e.g. google. Default google."}},
                "required": ["what"], "info": True},
}
HANDLERS = {"network": network}
