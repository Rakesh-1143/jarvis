"""Piece AK: PC health check. All OS calls are faked (no Windows needed)."""
import json
from datetime import date

import pytest

from jarvis.actions import pchealth as ph

BATTERY_XML = """<?xml version="1.0" encoding="utf-8"?>
<BatteryReport xmlns="http://schemas.microsoft.com/battery/2012">
  <Batteries>
    <Battery>
      <Id>DELL ABC</Id>
      <DesignCapacity>50000</DesignCapacity>
      <FullChargeCapacity>43500</FullChargeCapacity>
      <CycleCount>312</CycleCount>
    </Battery>
  </Batteries>
</BatteryReport>"""
NO_BATTERY_XML = """<?xml version="1.0"?><BatteryReport xmlns="http://schemas.microsoft.com/battery/2012">
<Batteries /></BatteryReport>"""


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(ph, "IS_WINDOWS", True)


# ---------- battery ----------
def test_parse_battery_xml():
    assert ph.parse_battery_xml(BATTERY_XML) == [{"design": 50000, "full": 43500, "cycles": 312}]
    assert ph.parse_battery_xml(NO_BATTERY_XML) == []


def test_battery_text():
    assert ph.battery_text([{"design": 50000, "full": 43500, "cycles": 312}]) == \
        "Battery health is 87 percent of its original capacity, 312 charge cycles."
    assert "getting worn" in ph.battery_text([{"design": 50000, "full": 35000, "cycles": 0}])
    assert "replacing" in ph.battery_text([{"design": 50000, "full": 20000, "cycles": None}])
    assert ph.battery_text([]) == "No battery found on this PC."
    assert ph.battery_text(None) == "I couldn't read the battery report."
    assert "not reported" in ph.battery_text([{"design": None, "full": 40000, "cycles": None}])
    # new battery can report more than design; never say over 100
    assert "100 percent" in ph.battery_text([{"design": 50000, "full": 51000, "cycles": 1}])


def test_battery_report_runs_powercfg_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr(ph.tempfile, "gettempdir", lambda: str(tmp_path))
    calls = []

    def fake_run(cmd, timeout=30):
        calls.append(cmd)
        (tmp_path / "jarvis_battery_report.xml").write_text(BATTERY_XML, encoding="utf-8")
        return ""
    monkeypatch.setattr(ph, "_run", fake_run)
    assert ph.battery_report() == [{"design": 50000, "full": 43500, "cycles": 312}]
    assert calls[0][:3] == ["powercfg", "/batteryreport", "/xml"]
    assert not (tmp_path / "jarvis_battery_report.xml").exists()


def test_battery_report_fails_softly(monkeypatch, tmp_path):
    monkeypatch.setattr(ph.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(ph, "_run", lambda cmd, timeout=30: "")  # no file written
    assert ph.battery_report() is None


# ---------- startup ----------
def test_startup_apps_skips_disabled(monkeypatch, tmp_path):
    folder = tmp_path / "Startup"
    folder.mkdir()
    (folder / "Notes.lnk").write_text("")
    (folder / "desktop.ini").write_text("")
    (folder / "Old.lnk").write_text("")
    reg = {
        ("HKCU", ph.RUN_KEYS[0][1]): {"OneDrive": "x", "Discord": "y"},
        ("HKLM", ph.RUN_KEYS[1][1]): {"SecurityHealth": "z", "onedrive": "dup"},
        ("HKCU", ph.APPROVED + "\\Run"): {"Discord": b"\x03\x00\x00"},
        ("HKCU", ph.APPROVED + "\\StartupFolder"): {"Old.lnk": b"\x03\x00", "Notes.lnk": b"\x02\x00"},
    }
    monkeypatch.setattr(ph, "_reg_values", lambda hive, path: reg.get((hive, path), {}))
    monkeypatch.setattr(ph, "_startup_folders", lambda: [str(folder)])
    assert ph.startup_apps() == ["Notes", "OneDrive", "SecurityHealth"]


def test_startup_text():
    assert ph.startup_text([]) == "No apps start with Windows."
    assert ph.startup_text(["OneDrive"]) == "1 app starts with Windows: OneDrive."
    many = [f"App{i}" for i in range(12)]
    t = ph.startup_text(many)
    assert t.startswith("12 apps start with Windows: App0, App1")
    assert "and 6 more" in t and "Task Manager" in t


def test_reg_values_without_winreg_is_empty():
    # On Linux winreg is missing; must not crash
    import sys
    if sys.platform != "win32":
        assert ph._reg_values("HKCU", ph.RUN_KEYS[0][1]) == {}


# ---------- updates ----------
def test_updates_text():
    today = date(2026, 11, 7)
    assert ph.updates_text({"last": "2026-11-05", "pending": 0}, today) == \
        "Windows is up to date, no updates waiting. Last update installed 2 days ago."
    t = ph.updates_text({"last": "2026-08-01", "pending": 3}, today)
    assert t.startswith("3 Windows updates are waiting") and "Settings > Windows Update" in t
    assert ph.updates_text({"last": "", "pending": 1}, today) == "1 Windows update is waiting to install."
    assert ph.updates_text({"last": "2026-11-07", "pending": -1}, today) == \
        "I couldn't count waiting updates. Last update installed today."
    assert ph.updates_text(None) == "I couldn't check Windows Update."


def test_updates_status_parses_json(monkeypatch):
    monkeypatch.setattr(ph, "_ps", lambda s, timeout=30: '{"last":"2026-11-01","pending":2}\r\n')
    assert ph.updates_status() == {"last": "2026-11-01", "pending": 2}
    monkeypatch.setattr(ph, "_ps", lambda s, timeout=30: "garbage")
    assert ph.updates_status() is None


def test_updates_script_is_read_only():
    s = ph.UPDATES_PS.lower()
    for bad in ("install(", "download(", "createupdateinstaller", "createupdatedownloader"):
        assert bad not in s


# ---------- antivirus ----------
def test_defender_on():
    d = {"AntivirusEnabled": True, "RealTimeProtectionEnabled": True, "AntivirusSignatureAge": 0,
         "QuickScanAge": 1, "FullScanAge": 4294967295}
    assert ph.antivirus_text({"defender": d}) == \
        "Microsoft Defender is on. Virus definitions are up to date. Last quick scan yesterday."


def test_defender_warnings():
    d = {"AntivirusEnabled": True, "RealTimeProtectionEnabled": False, "AntivirusSignatureAge": 12,
         "QuickScanAge": 4294967295, "FullScanAge": 30}
    t = ph.antivirus_text({"defender": d})
    assert "real-time protection is off" in t and "12 days old" in t
    assert "No quick scan yet" in t and "Last full scan 30 days ago" in t
    assert "is off" in ph.antivirus_text({"defender": {"AntivirusEnabled": False}})


def test_security_center_fallback(monkeypatch):
    outs = iter(["", json.dumps({"displayName": "Avast", "productState": 0x41000})])
    monkeypatch.setattr(ph, "_ps", lambda s, timeout=30: next(outs))
    data = ph.antivirus_status()
    assert data == {"products": [{"displayName": "Avast", "productState": 0x41000}]}
    assert ph.antivirus_text(data) == "Avast is on."
    assert ph.antivirus_text({"products": [{"displayName": "X", "productState": 0x40010}]}) == \
        "X is off, definitions out of date."
    assert ph.antivirus_text(None) == "I couldn't check the antivirus."


# ---------- intent ----------
def test_not_windows(monkeypatch):
    monkeypatch.setattr(ph, "IS_WINDOWS", False)
    assert "only on Windows" in ph.pc_health({})


def test_all_runs_every_part_and_survives_errors(win, monkeypatch):
    monkeypatch.setattr(ph, "battery_report", lambda: [{"design": 100, "full": 90, "cycles": 5}])
    monkeypatch.setattr(ph, "antivirus_status", lambda: None)
    monkeypatch.setattr(ph, "updates_status", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(ph, "startup_apps", lambda: ["OneDrive"])
    t = ph.pc_health({"what": "all"})
    assert t.startswith("Battery health is 90 percent")
    assert "couldn't check the antivirus" in t
    assert "I couldn't check updates." in t
    assert t.endswith("1 app starts with Windows: OneDrive.")


def test_single_part_and_bad_part(win, monkeypatch):
    monkeypatch.setattr(ph, "startup_apps", lambda: [])
    assert ph.pc_health({"what": "startup"}) == "No apps start with Windows."
    assert "I can check" in ph.pc_health({"what": "ram"})


def test_catalog_and_handlers_match():
    assert set(ph.CATALOG) == set(ph.HANDLERS) == {"pc_health"}
    c = ph.CATALOG["pc_health"]
    assert c["info"] is True and c["required"] == []
    assert set(c["properties"]["what"]["enum"]) == {"all", *ph.PARTS}
