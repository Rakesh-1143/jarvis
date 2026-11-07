"""Wi-Fi and Bluetooth on/off.

Uses the Windows Radio API (packages winrt-runtime + winrt-Windows.Devices.Radios).
If that is not installed or not allowed, opens the right Settings page instead.
"""
from __future__ import annotations

import asyncio
import os

_SETTINGS = {"wifi": "ms-settings:network-wifi", "bluetooth": "ms-settings:bluetooth"}
_NAMES = {"wifi": "Wi-Fi", "bluetooth": "Bluetooth"}


async def _set(kind: str, on: bool) -> bool:
    from winrt.windows.devices.radios import Radio, RadioKind, RadioState

    want = RadioKind.WI_FI if kind == "wifi" else RadioKind.BLUETOOTH
    await Radio.request_access_async()
    done = False
    for radio in await Radio.get_radios_async():
        if radio.kind == want:
            await radio.set_state_async(RadioState.ON if on else RadioState.OFF)
            done = True
    return done


def set_radio(kind: str, on: bool) -> bool:
    """True if the radio was switched. Separate function so tests can mock it."""
    return asyncio.run(_set(kind, on))


def radio(kind: str, args: dict) -> str:
    state = args.get("state")
    name = _NAMES[kind]
    if state not in ("on", "off"):
        os.startfile(_SETTINGS[kind])  # type: ignore[attr-defined]
        return f"Opening {name} settings."
    try:
        if set_radio(kind, state == "on"):
            return f"{name} is {state}."
    except Exception:
        pass
    os.startfile(_SETTINGS[kind])  # type: ignore[attr-defined]
    return f"I couldn't switch {name} myself, so I opened the settings."
