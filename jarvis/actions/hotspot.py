"""Piece BQ: Windows mobile hotspot.

"turn on hotspot", "turn off hotspot", "is my hotspot on", "how many devices are on my hotspot",
"what's my hotspot password".

Intent: hotspot {action: on|off|status|password}
  on / off  - start or stop sharing this PC's internet over Wi-Fi
  status    - (info) on or off, its name, how many devices are connected
  password  - the password is NEVER spoken: it is copied to the clipboard and shown in a small window

Uses WinRT NetworkOperatorTetheringManager.CreateFromConnectionProfile(GetInternetConnectionProfile())
(packages winrt-Windows.Networking.NetworkOperators + winrt-Windows.Networking.Connectivity).
If those are missing, there is no internet to share, or Windows refuses, it opens
ms-settings:network-mobilehotspot instead and says why.
Tests swap `_backend()`, `_open_settings()`, `_copy()` and `_show()` for fakes.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import threading

ACTIONS = ("on", "off", "status", "password")
_SYNONYMS = {
    "start": "on", "enable": "on", "turn_on": "on", "true": "on",
    "stop": "off", "disable": "off", "turn_off": "off", "false": "off",
    "info": "status", "devices": "status", "clients": "status", "name": "status", "check": "status",
    "passphrase": "password", "key": "password", "pass": "password",
}
SETTINGS_URI = "ms-settings:network-mobilehotspot"

# TetheringOperationStatus names -> what to say
_FAIL_WORDS = {
    "wi_fi_device_off": "Wi-Fi is turned off. Turn on Wi-Fi, then ask again.",
    "bluetooth_device_off": "Bluetooth is turned off, and the hotspot is set to share over Bluetooth.",
    "mobile_broadband_device_off": "The mobile data adapter is turned off.",
    "entitlement_check_timeout": "Your mobile operator didn't answer whether sharing is allowed.",
    "entitlement_check_failure": "Your mobile operator doesn't allow sharing this connection.",
    "operation_in_progress": "The hotspot is still switching. Try again in a moment.",
    "network_limited_connectivity": "Your internet connection is limited, so Windows won't share it.",
    "radio_restriction": "Windows can't start the hotspot on this Wi-Fi band right now.",
    "band_interference": "Windows can't start the hotspot on this Wi-Fi band right now.",
}
_CAPABILITY_WORDS = {
    "disabled_by_group_policy": "Your organisation has turned off the mobile hotspot on this PC.",
    "disabled_by_hardware_limitation": "This PC's Wi-Fi card can't make a hotspot.",
    "disabled_by_operator": "Your mobile operator doesn't allow sharing this connection.",
    "disabled_by_sku": "This edition of Windows doesn't allow the mobile hotspot.",
    "disabled_by_system_capability": "Windows has turned off the mobile hotspot on this PC.",
}


class HotspotError(Exception):
    """A reason the WinRT path can't be used. The message is said to the user."""


def _name(enum_value) -> str:
    return str(getattr(enum_value, "name", enum_value)).lower()


class WinrtHotspot:
    """The real Windows hotspot. All methods return plain Python values."""

    def __init__(self):
        from jarvis.winutil import com_init

        com_init()
        try:
            from winrt.windows.networking.connectivity import NetworkInformation
            from winrt.windows.networking.networkoperators import NetworkOperatorTetheringManager as Mgr
        except ImportError as e:
            raise HotspotError("The hotspot packages are not installed "
                               "(pip install winrt-Windows.Networking.NetworkOperators "
                               "winrt-Windows.Networking.Connectivity).") from e
        profile = NetworkInformation.get_internet_connection_profile()
        if profile is None:
            raise HotspotError("This PC is not connected to the internet, so there is nothing to share.")
        cap = _name(Mgr.get_tethering_capability_from_connection_profile(profile))
        if cap != "enabled":
            raise HotspotError(_CAPABILITY_WORDS.get(cap, "Windows says the hotspot can't be used on this PC."))
        self.m = Mgr.create_from_connection_profile(profile)

    def state(self) -> str:
        """on | off | in_transition | unknown"""
        return _name(self.m.tethering_operational_state)

    @staticmethod
    def _wait(op):
        async def go():
            return await op

        return asyncio.run(go())

    def start(self) -> tuple[str, str]:
        r = self._wait(self.m.start_tethering_async())
        return _name(r.status), str(r.additional_error_message or "")

    def stop(self) -> tuple[str, str]:
        r = self._wait(self.m.stop_tethering_async())
        return _name(r.status), str(r.additional_error_message or "")

    def ssid_and_password(self) -> tuple[str, str]:
        c = self.m.get_current_access_point_configuration()
        return str(c.ssid or ""), str(c.passphrase or "")

    def clients(self) -> tuple[int, int, list[str]]:
        """(connected count, max count, device names when Windows knows them)"""
        names: list[str] = []
        try:
            for client in self.m.get_tethering_clients():
                for host in client.host_names or []:
                    n = str(getattr(host, "display_name", "") or "")
                    if n and not re.fullmatch(r"[\d.:a-fA-F]+", n):  # skip bare IP addresses
                        names.append(n.split(".")[0])
                        break
        except Exception:
            pass
        return int(self.m.client_count), int(self.m.max_client_count), names


def _backend():
    if sys.platform != "win32":
        raise HotspotError("The mobile hotspot only works on Windows.")
    return WinrtHotspot()


def _open_settings() -> None:
    os.startfile(SETTINGS_URI)  # type: ignore[attr-defined]


def _copy(text: str) -> None:
    """Copy like generate does: skipped by Win+V history, cloud sync and Jarvis's own clipboard
    history, and cleared after 60 s if it is still there (review K4)."""
    from . import generate

    if not generate._copy(text):
        raise OSError("could not copy")
    generate._schedule_clear(text, 60)


def _show(title: str, text: str) -> None:
    """A small always-on-top message box, in its own thread so Jarvis keeps listening."""
    def box():
        try:
            import ctypes

            # MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x0 | 0x40 | 0x10000 | 0x40000)  # type: ignore[attr-defined]
        except Exception:
            pass

    threading.Thread(target=box, daemon=True, name="hotspot-password").start()


def _fallback(reason: str) -> str:
    try:
        _open_settings()
    except Exception:
        return f"{reason} Open Settings, Network, Mobile hotspot."
    return f"{reason} I opened the hotspot settings."


def _devices_words(count: int, most: int, names: list[str]) -> str:
    if count == 0:
        return "No devices are connected."
    who = f": {', '.join(names)}" if names else ""
    limit = f" (up to {most} can join)" if most else ""
    return f"{count} device{'s are' if count != 1 else ' is'} connected{who}{limit}."


def hotspot(args: dict) -> str:
    args = args or {}
    action = str(args.get("action") or args.get("state") or "status").strip().lower().replace(" ", "_")
    action = _SYNONYMS.get(action, action)
    if action not in ACTIONS:
        return "I can turn the hotspot on or off, tell you if it's on and who is connected, or show its password."
    try:
        hs = _backend()
    except HotspotError as e:
        return _fallback(str(e))
    except Exception as e:  # odd WinRT errors (no Wi-Fi adapter, service stopped)
        return _fallback(f"I couldn't reach the hotspot ({e}).")

    try:
        state = hs.state()
        if action == "status":
            if state == "on":
                ssid, _ = hs.ssid_and_password()
                count, most, names = hs.clients()
                named = f" Its name is {ssid}." if ssid else ""
                return f"Your hotspot is on.{named} {_devices_words(count, most, names)}"
            if state == "in_transition":
                return "Your hotspot is switching on or off right now."
            return "Your hotspot is off."

        if action == "password":
            ssid, password = hs.ssid_and_password()
            if not password:
                return _fallback("I couldn't read the hotspot password.")
            try:
                _copy(password)
                copied = "I copied the password to the clipboard and showed it on screen."
            except Exception:
                copied = "I showed the password on screen."
            _show("Mobile hotspot", f"Name: {ssid}\nPassword: {password}")
            return f"Your hotspot is called {ssid}. {copied}" if ssid else copied

        if action == "on":
            if state == "on":
                ssid, _ = hs.ssid_and_password()
                return f"Your hotspot is already on{f' as {ssid}' if ssid else ''}."
            status, extra = hs.start()
            if status in ("success", "already_on"):
                ssid, _ = hs.ssid_and_password()
                return f"Hotspot is on{f'. Connect to {ssid}' if ssid else ''}."
            return _fallback(_FAIL_WORDS.get(status, f"Windows couldn't start the hotspot{f' ({extra})' if extra else ''}."))

        # off
        if state == "off":
            return "Your hotspot is already off."
        status, extra = hs.stop()
        if status == "success":
            return "Hotspot is off."
        return _fallback(_FAIL_WORDS.get(status, f"Windows couldn't stop the hotspot{f' ({extra})' if extra else ''}."))
    except Exception as e:
        return _fallback(f"Something went wrong with the hotspot ({e}).")


# ---------- phrases (for nlu_features) ----------

_HS = r"(?:(?:my|the|mobile|wi-?fi|wifi|personal|laptop'?s?|pc'?s?) )*hot ?spot"


def parse(text: str):
    """(intent, args) or None. Call before the winsettings rule ('hotspot settings' stays with winsettings)."""
    t = re.sub(r"\s+", " ", (text or "").lower()).strip().rstrip("?.! ")
    if not t or not re.search(r"hot ?spot", t) or re.search(r"\bsettings?\b", t):
        return None
    if re.fullmatch(rf"(?:please )?(?:turn|switch|put) on {_HS}|(?:please )?(?:turn|switch) {_HS} on"
                    rf"|(?:start|enable|share (?:my )?internet (?:with|using|over|via))(?: the| my)? {_HS}"
                    rf"|{_HS} on", t):
        return "hotspot", {"action": "on"}
    if re.fullmatch(rf"(?:please )?(?:turn|switch) off {_HS}|(?:please )?(?:turn|switch) {_HS} off"
                    rf"|(?:stop|disable|close)(?: the| my)? {_HS}|{_HS} off", t):
        return "hotspot", {"action": "off"}
    if re.search(r"\b(?:password|passcode|passphrase|pass word|key)\b", t) and re.fullmatch(
            rf"(?:what(?:'s|s| is)|tell me|show(?: me)?|give me|copy)(?: the| my)? {_HS} (?:password|passcode|passphrase|pass word|key)"
            rf"|(?:what(?:'s|s| is)|show(?: me)?)(?: the)? (?:password|passcode|passphrase|key) (?:of|for) {_HS}", t):
        return "hotspot", {"action": "password"}
    if re.fullmatch(rf"(?:is|is the|is my) {_HS} (?:on|off|running|working|active)"
                    rf"|(?:how many|which|what) (?:devices|people|phones|clients)(?: are)? (?:on|connected to|using|joined) {_HS}"
                    rf"|(?:who(?:'s| is)) (?:on|connected to|using) {_HS}"
                    rf"|(?:what(?:'s| is)) (?:the )?(?:name of )?{_HS}(?: name| status)?|{_HS} status", t):
        return "hotspot", {"action": "status"}
    return None


CATALOG: dict[str, dict] = {
    "hotspot": {
        "description": ("Windows mobile hotspot (share this PC's internet over Wi-Fi): turn it on or off, say if it "
                        "is on with its name and how many devices are connected, or copy the password to the "
                        "clipboard and show it on screen (the password is never spoken or returned)."),
        "properties": {"action": {"type": "string", "enum": list(ACTIONS)}},
        "required": ["action"],
    },
}

HANDLERS = {"hotspot": hotspot}
