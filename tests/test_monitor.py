import os
import sys
import threading
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import monitor  # noqa: E402

S = dict(monitor.DEFAULTS)


@pytest.fixture(autouse=True)
def clean():
    monitor.stop()
    monitor.reset()
    yield
    monitor.stop()
    monitor.reset()


def snap(battery=None, plugged=None, cpu=None, disk=None):
    return {"battery": battery, "plugged": plugged, "cpu": cpu, "disk_free_gb": disk}


class FakePs:
    def __init__(self, percent=50, plugged=False, cpu=10.0, free_gb=100, battery=True):
        self.percent, self.plugged, self.cpu, self.free_gb, self.battery = percent, plugged, cpu, free_gb, battery

    def sensors_battery(self):
        return NS(percent=self.percent, power_plugged=self.plugged) if self.battery else None

    def cpu_percent(self, interval=None):
        return self.cpu

    def disk_usage(self, path):
        return NS(free=self.free_gb * 1024**3)


def test_battery_low_speaks_once_then_rearms():
    assert monitor.check(snap(15, False), S) == ["Battery is low, 15 percent. Please plug in the charger."]
    assert monitor.check(snap(14, False), S) == []  # no spam
    assert monitor.check(snap(14, True), S) == []  # plugged in -> cleared
    assert len(monitor.check(snap(13, False), S)) == 1  # unplugged again -> speaks again


def test_battery_low_not_when_charging():
    assert monitor.check(snap(10, True), S) == []


def test_battery_full():
    assert monitor.check(snap(100, True), S) == ["Battery is fully charged. You can unplug the charger."]
    assert monitor.check(snap(100, True), S) == []
    assert monitor.check(snap(100, False), S) == []  # unplugged -> cleared
    assert len(monitor.check(snap(100, True), S)) == 1


def test_cpu_must_stay_high_for_two_minutes():
    assert monitor.check(snap(cpu=95), S, now=0) == []
    assert monitor.check(snap(cpu=97), S, now=60) == []
    msg = monitor.check(snap(cpu=96), S, now=120)
    assert msg == ["CPU has been over 90 percent for 2 minutes. Something may be stuck."]
    assert monitor.check(snap(cpu=99), S, now=180) == []
    assert monitor.check(snap(cpu=20), S, now=240) == []  # dropped -> timer resets
    assert monitor.check(snap(cpu=95), S, now=300) == []
    assert len(monitor.check(snap(cpu=95), S, now=420)) == 1


def test_cpu_short_spike_is_ignored():
    monitor.check(snap(cpu=95), S, now=0)
    monitor.check(snap(cpu=30), S, now=60)
    assert monitor.check(snap(cpu=95), S, now=130) == []


def test_disk_low():
    assert monitor.check(snap(disk=3.24), S) == ["Disk space is low, only 3.2 gigabytes free."]
    assert monitor.check(snap(disk=3.0), S) == []
    assert monitor.check(snap(disk=5.5), S) == []  # not enough to re-arm (needs 6)
    assert monitor.check(snap(disk=4.0), S) == []
    monitor.check(snap(disk=7), S)  # cleared
    assert len(monitor.check(snap(disk=4.0), S)) == 1


def test_missing_parts_are_skipped():
    assert monitor.check(snap(), S) == []


def test_config_thresholds():
    s = monitor.settings({"alerts": {"battery_low": 30, "disk_low_gb": 10}})
    assert s["battery_low"] == 30 and s["cpu_high"] == 90
    assert len(monitor.check(snap(25, False, disk=8), s)) == 2


def test_turn_off_and_on():
    assert monitor.alerts({"state": "off", "kind": "battery"}) == "Battery alerts turned off."
    assert monitor.check(snap(5, False), S) == []
    assert monitor.alerts({}) == "Alerts are on for cpu, disk."
    assert monitor.alerts({"state": "on"}) == "All alerts turned on."
    assert len(monitor.check(snap(5, False), S)) == 1
    assert monitor.alerts({"state": "off"}) == "All alerts turned off."
    assert monitor.alerts({}) == "All alerts are off."
    assert monitor.check(snap(5, False, cpu=99, disk=1), S, now=0) == []


def test_read_with_fake_psutil():
    s = monitor.read(FakePs(percent=42, plugged=True, cpu=12.5, free_gb=50), "C:\\")
    assert s == {"battery": 42.0, "plugged": True, "cpu": 12.5, "disk_free_gb": 50.0}


def test_read_desktop_without_battery():
    s = monitor.read(FakePs(battery=False), "/")
    assert s["battery"] is None and s["plugged"] is None


def test_start_thread_speaks_and_stops():
    said, got = [], threading.Event()

    def say(text):
        said.append(text)
        got.set()

    t = monitor.start(say, cfg={"alerts": {"interval": 60}}, ps=FakePs(percent=10, plugged=False))
    assert t is not None and t.daemon
    assert got.wait(5)
    assert monitor.start(say, ps=FakePs()) is t  # only one thread
    monitor.stop()
    assert not t.is_alive()
    assert said == ["Battery is low, 10 percent. Please plug in the charger."]


def test_start_disabled_in_config():
    monitor.start(lambda t: None, cfg={"alerts": {"enabled": False}}, ps=FakePs())
    assert monitor.alerts({}) == "All alerts are off."


def test_catalog_matches_handlers():
    assert set(monitor.CATALOG) == set(monitor.HANDLERS) == {"alerts"}
    for spec in monitor.CATALOG.values():
        assert {"description", "properties", "required"} <= set(spec)
