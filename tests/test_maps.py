"""Piece AV: maps.py (travel time, directions). No network: geocode/route/fetch are faked."""
import urllib.parse

import pytest

from jarvis.actions import maps

HYD = (17.385, 78.4867, "Hyderabad")
VIZAG = (17.6868, 83.2185, "Visakhapatnam")
AIRPORT = (17.2403, 78.4294, "Rajiv Gandhi International Airport")
_REAL_SETTINGS = maps._settings


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    maps._cache.clear()
    monkeypatch.setattr(maps, "_settings", lambda: {"home": "Hyderabad", "units": "km"})
    monkeypatch.setattr(maps.time, "sleep", lambda s: None)


def _fake_geo(monkeypatch, table, calls=None):
    def geo(place, near=None):
        if calls is not None:
            calls.append((place, near))
        return table.get(place.lower())
    monkeypatch.setattr(maps, "geocode", geo)


# ---------- text cleaning ----------

@pytest.mark.parametrize("said,place", [
    ("how long to drive to Hyderabad", "Hyderabad"),
    ("how far is the airport?", "the airport"),
    ("directions to Charminar", "Charminar"),
    ("how long does it take to get to Vizag", "Vizag"),
    ("Hyderabad", "Hyderabad"),
    ("navigate to Gachibowli please", "Gachibowli"),
    ("how long to walk to the park", "the park"),
])
def test_clean_place(said, place):
    assert maps._clean_place(said) == place


def test_split_from():
    assert maps._split_from("Hyderabad from Vizag", "") == ("Hyderabad", "Vizag")
    assert maps._split_from("from Vizag to Hyderabad", "") == ("Hyderabad", "Vizag")
    assert maps._split_from("Hyderabad", "Vizag") == ("Hyderabad", "Vizag")
    assert maps._split_from("how long from Vizag to Hyderabad", "") == ("Hyderabad", "Vizag")
    assert maps._split_from("how far is Hyderabad from Vizag", "") == ("Hyderabad", "Vizag")


def test_mode_words():
    assert maps._mode({"mode": "walk"}) == "walking"
    assert maps._mode({"mode": "bus"}) == "transit"
    assert maps._mode({}, "how long to walk to the park") == "walking"
    assert maps._mode({}, "Hyderabad") == "driving"


def test_say_duration_and_distance():
    assert maps.say_duration(30) == "1 minute"
    assert maps.say_duration(25 * 60) == "25 minutes"
    assert maps.say_duration(130 * 60) == "2 hours 10 minutes"
    assert maps.say_duration(60 * 60) == "1 hour"
    assert maps.say_duration((11 * 60 + 50) * 60) == "12 hours"
    assert maps.say_distance(0.45, "km") == "450 metres"
    assert maps.say_distance(3.26, "km") == "3.3 kilometres"
    assert maps.say_distance(625.4, "km") == "625 kilometres"
    assert maps.say_distance(100, "miles") == "62 miles"


def test_straight_km():
    assert 490 < maps.straight_km(HYD, VIZAG) < 515


def test_clean_untrusted_text():
    assert maps._clean("<b>Evil</b> place; rm -rf $HOME {x}") == "Evil place rm -rf HOME x"
    assert len(maps._clean("a" * 200)) == 60


# ---------- travel_time ----------

def test_travel_time_driving(monkeypatch):
    calls = []
    _fake_geo(monkeypatch, {"hyderabad": HYD, "vizag": VIZAG}, calls)
    monkeypatch.setattr(maps, "route", lambda a, b: (9 * 3600 + 20 * 60, 620_000))
    out = maps.travel_time({"to": "how long to drive to Vizag"})
    assert out == ("Driving to Visakhapatnam from home takes about 9 hours 20 minutes. "
                   "It's 620 kilometres. That's normal road time, without live traffic.")
    assert calls[0] == ("Hyderabad", None)
    assert calls[1][1] == HYD  # destination searched near the start


def test_travel_time_from_place(monkeypatch):
    _fake_geo(monkeypatch, {"hyderabad": HYD, "vizag": VIZAG})
    monkeypatch.setattr(maps, "route", lambda a, b: (3600, 50_000))
    out = maps.travel_time({"to": "Hyderabad", "from": "Vizag"})
    assert "Driving to Hyderabad from Vizag takes about 1 hour" in out


def test_travel_time_walking(monkeypatch):
    _fake_geo(monkeypatch, {"hyderabad": HYD, "the park": AIRPORT})
    monkeypatch.setattr(maps, "route", lambda a, b: (600, 2_500))
    out = maps.travel_time({"to": "the park", "mode": "walking"})
    assert out.startswith("Walking to Rajiv Gandhi International Airport from home takes about 30 minutes")
    assert "live traffic" not in out


def test_travel_time_no_road_uses_straight_line(monkeypatch):
    _fake_geo(monkeypatch, {"hyderabad": HYD, "vizag": VIZAG})
    monkeypatch.setattr(maps, "route", lambda a, b: None)
    out = maps.travel_time({"to": "Vizag"})
    assert "couldn't get a road route" in out and "straight line" in out and "kilometres" in out


def test_travel_time_route_error_soft(monkeypatch):
    _fake_geo(monkeypatch, {"hyderabad": HYD, "vizag": VIZAG})

    def boom(a, b):
        raise OSError("offline")
    monkeypatch.setattr(maps, "route", boom)
    assert "straight line" in maps.travel_time({"to": "Vizag"})


def test_travel_time_offline(monkeypatch):
    def boom(place, near=None):
        raise OSError("offline")
    monkeypatch.setattr(maps, "geocode", boom)
    assert "couldn't reach the map service" in maps.travel_time({"to": "Vizag"})


def test_travel_time_not_found(monkeypatch):
    _fake_geo(monkeypatch, {"hyderabad": HYD})
    assert "couldn't find Atlantis" in maps.travel_time({"to": "Atlantis"})


def test_travel_time_needs_start(monkeypatch):
    monkeypatch.setattr(maps, "_settings", lambda: {"home": "", "units": "km"})
    assert "starting from" in maps.travel_time({"to": "Vizag"})


def test_travel_time_needs_place():
    assert maps.travel_time({}) == "Where do you want to go?"


def test_travel_time_transit_points_to_directions():
    assert "Google Maps" in maps.travel_time({"to": "Vizag", "mode": "bus"})


def test_travel_time_miles(monkeypatch):
    monkeypatch.setattr(maps, "_settings", lambda: {"home": "Hyderabad", "units": "miles"})
    _fake_geo(monkeypatch, {"hyderabad": HYD, "vizag": VIZAG})
    monkeypatch.setattr(maps, "route", lambda a, b: (3600, 160_934))
    assert "100 miles" in maps.travel_time({"to": "Vizag"})


# ---------- real geocode/route parsing (fetch faked) ----------

def test_geocode_parses_and_caches(monkeypatch):
    urls = []

    def fetch(url):
        urls.append(url)
        return [{"lat": "17.24", "lon": "78.43", "name": "RGIA <script>",
                 "display_name": "RGIA, Shamshabad, India"}]
    monkeypatch.setattr(maps, "_fetch_json", fetch)
    hit = maps.geocode("the airport", near=HYD)
    assert hit == (17.24, 78.43, "RGIA")  # tag text dropped
    q = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
    assert q["q"] == ["the airport"] and q["bounded"] == ["0"] and "viewbox" in q
    assert maps.geocode("The Airport", near=HYD) == hit  # cached
    assert len(urls) == 1


def test_geocode_empty_and_bad(monkeypatch):
    monkeypatch.setattr(maps, "_fetch_json", lambda url: [])
    assert maps.geocode("nowhere") is None
    monkeypatch.setattr(maps, "_fetch_json", lambda url: [{"lat": "x"}])
    assert maps.geocode("bad") is None


def test_geocode_rate_limit(monkeypatch):
    sleeps = []
    monkeypatch.setattr(maps.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(maps, "_fetch_json", lambda url: [])
    maps.geocode("one")
    maps.geocode("two")
    assert sleeps and 0 < sleeps[-1] <= 1.0


def test_route_parses(monkeypatch):
    urls = []

    def fetch(url):
        urls.append(url)
        return {"code": "Ok", "routes": [{"duration": 1200.5, "distance": 15000}]}
    monkeypatch.setattr(maps, "_fetch_json", fetch)
    assert maps.route(HYD, AIRPORT) == (1200.5, 15000.0)
    assert "78.486700,17.385000;78.429400,17.240300" in urls[0]  # OSRM wants lon,lat
    monkeypatch.setattr(maps, "_fetch_json", lambda url: {"code": "NoRoute", "routes": []})
    assert maps.route(HYD, AIRPORT) is None


def test_user_agent_header(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"[]"

    def urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        return Resp()
    monkeypatch.setattr(maps.urllib.request, "urlopen", urlopen)
    assert maps._fetch_json("https://example.org") == []
    assert seen["ua"].startswith("JarvisVoiceAssistant")


# ---------- directions ----------

def test_directions_opens_maps(monkeypatch):
    opened = []
    monkeypatch.setattr(maps.webbrowser, "open", lambda url: opened.append(url) or True)
    out = maps.directions({"to": "directions to the airport"})
    assert out == "Opening directions to the airport in Google Maps."
    q = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query)
    assert opened[0].startswith("https://www.google.com/maps/dir/?api=1")
    assert q["destination"] == ["the airport"] and q["travelmode"] == ["driving"] and "origin" not in q


def test_directions_from_home_by_bus(monkeypatch):
    opened = []
    monkeypatch.setattr(maps.webbrowser, "open", lambda url: opened.append(url) or True)
    out = maps.directions({"to": "Charminar", "from": "home", "mode": "bus"})
    assert out == "Opening bus and train directions to Charminar from Hyderabad in Google Maps."
    q = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query)
    assert q["origin"] == ["Hyderabad"] and q["travelmode"] == ["transit"]


def test_directions_url_is_encoded():
    url = maps.directions_url("A&B=c", "", "walking")
    assert url.startswith(maps.GMAPS_URL + "&") and "A%26B%3Dc" in url and "travelmode=walking" in url


def test_directions_needs_place_and_browser_fail(monkeypatch):
    assert maps.directions({}) == "Where do you want directions to?"
    monkeypatch.setattr(maps.webbrowser, "open", lambda url: False)
    assert "couldn't open the browser" in maps.directions({"to": "Vizag"})


def test_catalog_matches_handlers():
    assert set(maps.CATALOG) == set(maps.HANDLERS) == {"travel_time", "directions"}
    assert maps.CATALOG["travel_time"]["info"] is True
    assert not maps.CATALOG["directions"].get("info")


def test_settings_from_config(monkeypatch):
    from jarvis import config
    monkeypatch.setattr(config, "load_config",
                        lambda: {"weather": {"city": "Pune", "units": "imperial"}})
    assert _REAL_SETTINGS() == {"home": "Pune", "units": "miles"}
    monkeypatch.setattr(config, "load_config",
                        lambda: {"maps": {"home": "Gachibowli", "units": "km"}, "weather": {"city": "Pune"}})
    assert _REAL_SETTINGS() == {"home": "Gachibowli", "units": "km"}
