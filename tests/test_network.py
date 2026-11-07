"""Piece J: network info. All OS and internet calls are mocked."""
import io
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.actions import network as net  # noqa: E402

NETSH = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    State                  : connected
    SSID                   : HomeNet 5G
    BSSID                  : aa:bb:cc:dd:ee:ff
    Radio type             : 802.11ax
    Receive rate (Mbps)    : 1201
    Signal                 : 87%
"""
NETSH_OFF = """
    Name                   : Wi-Fi
    State                  : disconnected
"""
PING_WIN = """
Pinging google.com [142.250.183.14] with 32 bytes of data:
Reply from 142.250.183.14: bytes=32 time=21ms TTL=117
Reply from 142.250.183.14: bytes=32 time=23ms TTL=117
Request timed out.
Reply from 142.250.183.14: bytes=32 time=22ms TTL=117

Ping statistics for 142.250.183.14:
    Packets: Sent = 4, Received = 3, Lost = 1 (25% loss),
Approximate round trip times in milli-seconds:
    Minimum = 21ms, Maximum = 23ms, Average = 22ms
"""
PING_LINUX = """64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=10.2 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=11.8 ms
rtt min/avg/max/mdev = 10.2/11.0/11.8/0.8 ms"""
PING_FAIL = "Request timed out.\nRequest timed out.\n"


def test_online_and_offline():
    with mock.patch.object(net, "_get", return_value=b"ok"):
        assert net.network({"what": "online"}) == "Yes, you're online."
    with mock.patch.object(net, "_get", side_effect=OSError):
        assert net.network({"what": "online"}).startswith("No, you're offline")
    with mock.patch.object(net, "_get", side_effect=[OSError, b""]):  # first URL fails, second works
        assert net.is_online()


def test_ip():
    with mock.patch.object(net, "local_ip", return_value="192.168.1.5"), \
         mock.patch.object(net, "_get", return_value=b"49.37.1.2\n"):
        assert net.network({"what": "ip"}) == "Your local IP is 192.168.1.5. Your public IP is 49.37.1.2."
    with mock.patch.object(net, "local_ip", return_value="192.168.1.5"), \
         mock.patch.object(net, "_get", side_effect=OSError):
        assert net.network({"what": "ip"}).endswith("I couldn't get your public IP.")
    with mock.patch.object(net, "local_ip", return_value=None), \
         mock.patch.object(net, "public_ip", return_value=None):
        assert "may be offline" in net.network({"what": "ip"})


def test_wifi():
    with mock.patch.object(net.sys, "platform", "win32"), mock.patch.object(net, "_run", return_value=NETSH):
        assert net.network({"what": "wifi"}) == "You're on Wi-Fi HomeNet 5G, signal 87 percent."
    with mock.patch.object(net.sys, "platform", "win32"), mock.patch.object(net, "_run", return_value=NETSH_OFF):
        assert net.network({"what": "wifi"}) == "You're not connected to Wi-Fi."
    assert net.wifi_info.__doc__  # parser does not need Windows
    with mock.patch.object(net, "_run", return_value=NETSH):
        w = net.wifi_info()
    assert w == {"ssid": "HomeNet 5G", "signal": "87", "state": "connected", "rate": "1201"}


def test_speed():
    data = io.BytesIO(b"x" * 2_000_000)
    resp = mock.MagicMock()
    resp.__enter__.return_value = data
    clock = iter([0.0])  # start at 0 s, every later reading is 1.6 s
    with mock.patch.object(net.urllib.request, "urlopen", return_value=resp), \
         mock.patch.object(net.time, "perf_counter", side_effect=lambda: next(clock, 1.6)):
        mbps = net.speed_test()
    assert 9 < mbps < 11  # 2 MB in 1.6 s = 10 Mbps
    with mock.patch.object(net, "speed_test", return_value=95.4):
        assert net.network({"what": "speed"}) == "Your download speed is about 95 megabits per second. That's fast."
    with mock.patch.object(net, "speed_test", return_value=None):
        assert "couldn't run the speed test" in net.network({"what": "speed"})


def test_ping_windows_output():
    with mock.patch.object(net.sys, "platform", "win32"), mock.patch.object(net, "_run", return_value=PING_WIN) as r:
        out = net.network({"what": "ping", "host": "google"})
    assert r.call_args[0][0] == ["ping", "-n", "4", "google.com"]
    assert out == "Google replied in 22 milliseconds. 1 of 4 pings were lost."


def test_ping_linux_output_and_fail():
    with mock.patch.object(net, "_run", return_value=PING_LINUX):
        assert net.ping("1.1.1.1", count=2) == (11, 2, 2)
    with mock.patch.object(net, "_run", return_value=PING_FAIL):
        assert net.network({"what": "ping", "host": "example.org"}) == "No reply from example.org."


def test_ping_router():
    ipconfig = "   Default Gateway . . . . . . . . . : 192.168.1.1\n"
    with mock.patch.object(net.sys, "platform", "win32"), \
         mock.patch.object(net, "_run", side_effect=[ipconfig, PING_WIN]) as r:
        assert net.network({"what": "ping", "host": "router"}).startswith("Router replied in 22")
    assert r.call_args[0][0][-1] == "192.168.1.1"


def test_host_names():
    assert net._host_for("") == "google.com"
    assert net._host_for("youtube") == "youtube.com"
    assert net._host_for("github") == "github.com"
    assert net._host_for("bbc.co.uk") == "bbc.co.uk"


def test_unknown_what_and_wiring():
    assert "I can check" in net.network({"what": "banana"})
    assert set(net.CATALOG) == set(net.HANDLERS) == {"network"}
    assert net.CATALOG["network"]["info"] is True
