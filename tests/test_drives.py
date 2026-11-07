"""Tests for actions/drives.py with fake drives (no Windows needed)."""
import types

import pytest

from jarvis.actions import drives as dr

GB = 1024 ** 3


def _d(letter, kind, label="", total=100 * GB, free=40 * GB):
    return {"letter": letter, "mount": f"{letter}:\\", "label": label, "kind": kind, "total": total, "free": free}


@pytest.fixture
def fake(monkeypatch):
    state = {"drives": [_d("C", "fixed", "Windows", 500 * GB, 120 * GB), _d("D", "fixed", "", 1000 * GB, 900 * GB),
                        _d("E", "removable", "KINGSTON", 32 * GB, 10 * GB)],
             "opened": [], "ejected": [], "eject_works": True}

    def eject(letter):
        state["ejected"].append(letter)
        if state["eject_works"]:
            state["drives"] = [d for d in state["drives"] if d["letter"] != letter]

    monkeypatch.setattr(dr, "_on_windows", lambda: True)
    monkeypatch.setattr(dr, "_drives", lambda: list(state["drives"]))
    monkeypatch.setattr(dr, "_open", lambda m: state["opened"].append(m))
    monkeypatch.setattr(dr, "_eject", eject)
    monkeypatch.setattr(dr, "EJECT_WAIT", 0.0)
    monkeypatch.setattr(dr.time, "sleep", lambda s: None)
    monkeypatch.setenv("SystemDrive", "C:")
    return state


def test_list_all(fake):
    out = dr.drives({"action": "list"})
    assert out.startswith("You have 3 drives")
    assert "pen drive E (KINGSTON)" in out and "local disk C (Windows)" in out


def test_is_pen_drive_connected(fake):
    assert dr.drives({"action": "list", "drive": "pen drive"}).startswith("Yes, pen drive E")
    fake["drives"] = fake["drives"][:2]
    assert dr.drives({"action": "list", "drive": "my pen drive"}) == "No, I can't see a pen drive."


def test_space_one_drive_by_letter_forms(fake):
    for word in ("D", "d:", "d drive", "drive d", "dee drive", "D:\\"):
        out = dr.drives({"action": "space", "drive": word})
        assert out.startswith("local disk D has 900 GB free of 1000 GB (90% free)"), word


def test_space_pen_drive_and_all(fake):
    assert "10 GB free of 32 GB" in dr.drives({"action": "space", "drive": "usb"})
    out = dr.drives({"action": "space"})
    assert out.count("free of") == 3


def test_space_unknown_drive(fake):
    assert dr.drives({"action": "space", "drive": "z"}) == "I can't find a Z drive."


def test_label_match(fake):
    assert "pen drive E" in dr.drives({"action": "space", "drive": "kingston"})


def test_sizes():
    assert dr._size(None) == "unknown"
    assert dr._size(512 * 1024 ** 2) == "512 MB"
    assert dr._size(int(1.5 * GB)) == "1.5 GB"
    assert dr._size(2048 * GB) == "2.0 TB"


def test_open_default_is_pen_drive(fake):
    assert dr.drives({"action": "open"}) == "Opening pen drive E (KINGSTON)."
    assert fake["opened"] == ["E:\\"]
    dr.drives({"action": "open", "drive": "d"})
    assert fake["opened"][-1] == "D:\\"


def test_open_two_pen_drives_asks(fake):
    fake["drives"].append(_d("F", "removable", "SANDISK"))
    out = dr.drives({"action": "open", "drive": "pen drive"})
    assert "more than one" in out and "Which drive letter" in out
    assert fake["opened"] == []


def test_eject_ok(fake):
    out = dr.drives({"action": "eject", "drive": "pen drive"})
    assert out == "pen drive E (KINGSTON) is ejected. You can unplug it now."
    assert fake["ejected"] == ["E"]


def test_eject_busy(fake):
    fake["eject_works"] = False
    out = dr.drives({"action": "eject"})
    assert "still open" in out


def test_eject_never_system_drive(fake):
    assert "Windows drive" in dr.drives({"action": "eject", "drive": "c"})
    assert fake["ejected"] == []


def test_eject_network_refused(fake):
    fake["drives"].append(_d("N", "network", "share"))
    assert "can't be ejected" in dr.drives({"action": "eject", "drive": "n"})


def test_eject_no_pen_drive(fake):
    fake["drives"] = fake["drives"][:2]
    assert dr.drives({"action": "eject"}) == "I can't find a pen drive. Is it plugged in?"


def test_external_includes_labelled_fixed(fake):
    fake["drives"].append(_d("G", "fixed", "Seagate"))
    out = dr.drives({"action": "list", "drive": "external drive"})
    assert "E" in out and "G (Seagate)" in out and "C (Windows)" not in out


def test_eject_bad_letter_rejected():
    with pytest.raises(ValueError):
        dr._eject("C;rm")


def test_bad_action(fake):
    assert "I can list" in dr.drives({"action": "format"})


def test_not_windows(monkeypatch):
    monkeypatch.setattr(dr, "_on_windows", lambda: False)
    assert "only work on Windows" in dr.drives({"action": "list"})


def test_real_reader_with_fake_psutil(monkeypatch):
    parts = [types.SimpleNamespace(device="C:\\", mountpoint="C:\\", opts="rw,fixed"),
             types.SimpleNamespace(device="E:\\", mountpoint="E:\\", opts="rw,removable"),
             types.SimpleNamespace(device="F:\\", mountpoint="F:\\", opts="cdrom")]

    def usage(m):
        if m.startswith("F"):
            raise OSError("not ready")
        return types.SimpleNamespace(total=10 * GB, free=5 * GB)

    fake_psutil = types.SimpleNamespace(disk_partitions=lambda all=False: parts, disk_usage=usage)
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)
    monkeypatch.setattr(dr, "_drive_type", lambda m: "unknown")
    monkeypatch.setattr(dr, "_volume_label", lambda m: "")
    out = dr._drives()
    assert [(d["letter"], d["kind"]) for d in out] == [("C", "fixed"), ("E", "removable")]  # empty CD left out


@pytest.mark.parametrize("text,args", [
    ("what drives are connected", {"action": "list"}),
    ("which drives do I have", {"action": "list"}),
    ("list my drives", {"action": "list"}),
    ("is my pen drive connected", {"action": "list", "drive": "pen drive"}),
    ("is the usb plugged in", {"action": "list", "drive": "usb"}),
    ("how much space on D drive", {"action": "space", "drive": "d drive"}),
    ("how much space is left on my pen drive", {"action": "space", "drive": "pen drive"}),
    ("how much free space is on e drive", {"action": "space", "drive": "e drive"}),
    ("how full is my d drive", {"action": "space", "drive": "d drive"}),
    ("free space on all drives", {"action": "space"}),
    ("open my pen drive", {"action": "open", "drive": "pen drive"}),
    ("open d drive", {"action": "open", "drive": "d drive"}),
    ("eject my pen drive", {"action": "eject", "drive": "pen drive"}),
    ("safely remove the usb drive", {"action": "eject", "drive": "usb drive"}),
    ("eject the sd card", {"action": "eject", "drive": "sd card"}),
])
def test_parse(text, args):
    assert dr.parse(text) == ("drives", args)


@pytest.mark.parametrize("text", [
    "how much disk space", "open chrome", "drive to work", "how long to drive to delhi",
    "remove this file", "eject", "open my documents", "what is my storage", "",
])
def test_parse_no_match(text):
    assert dr.parse(text) is None


def test_catalog_matches_handlers():
    assert set(dr.CATALOG) == set(dr.HANDLERS) == {"drives"}
    assert dr.CATALOG["drives"]["properties"]["action"]["enum"] == list(dr.ACTIONS)
