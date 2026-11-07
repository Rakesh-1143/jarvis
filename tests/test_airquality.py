"""Piece BD: airquality.py (AQI, sun times, rain soon, UV). No network: _fetch_json is faked."""
import datetime as dt
import urllib.parse

import pytest

from jarvis.actions import airquality as aq

HYD = (17.385, 78.4867, "Hyderabad")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    aq._geo_cache.clear()
    monkeypatch.setattr(aq, "_default_city", lambda: "Hyderabad")


def _fake_fetch(monkeypatch, routes, calls=None):
    """routes: {url prefix: json or Exception}."""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        for prefix, val in routes.items():
            if url.startswith(prefix):
                if isinstance(val, Exception):
                    raise val
                return val
        raise AssertionError("unexpected url " + url)
    monkeypatch.setattr(aq, "_fetch_json", fetch)


def _geo(name="Hyderabad", country="India"):
    return {"results": [{"name": name, "latitude": 17.385, "longitude": 78.4867, "country": country}]}


def _forecast(now="2026-11-07T10:00", probs=None, mm=None, uvs=None, sunrise=None, sunset=None, uvmax=None):
    base = dt.datetime.fromisoformat("2026-11-07T00:00")
    times = [(base + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(48)]
    return {
        "utc_offset_seconds": 19800,
        "hourly": {
            "time": times,
            "precipitation_probability": probs if probs is not None else [0] * 48,
            "precipitation": mm if mm is not None else [0.0] * 48,
            "uv_index": uvs if uvs is not None else [0.0] * 48,
        },
        "daily": {
            "time": ["2026-11-07", "2026-11-08"],
            "sunrise": sunrise or ["2026-11-07T06:12", "2026-11-08T06:13"],
            "sunset": sunset or ["2026-11-07T17:41", "2026-11-08T17:40"],
            "uv_index_max": uvmax if uvmax is not None else [7.4, 7.2],
        },
    }


def _at_local(monkeypatch, local: str):
    """Freeze the place's local time (offset +5:30 like the fake forecast)."""
    t = dt.datetime.fromisoformat(local)
    orig = aq._local_now
    monkeypatch.setattr(aq, "_local_now", lambda data, now=None: t)
    return orig


# ---------- city text ----------

@pytest.mark.parametrize("said,city", [
    ("in Hyderabad", "Hyderabad"),
    ("for Delhi today", "Delhi"),
    ("Mumbai?", "Mumbai"),
    ("here", ""),
    ("", ""),
    (None, ""),
    ("my area", ""),
])
def test_clean_city(said, city):
    assert aq._clean_city(said) == city


def test_clean_strips_tags_and_symbols():
    assert aq._clean("<b>Hyd</b>{}$erabad") == "Hyd erabad"
    assert len(aq._clean("x" * 200)) == 60


# ---------- geocode ----------

def test_geocode_uses_open_meteo_and_caches(monkeypatch):
    calls = []
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo()}, calls)
    assert aq.geocode("Hyderabad") == HYD
    assert aq.geocode("hyderabad") == HYD
    assert len(calls) == 1
    q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)
    assert q["name"] == ["Hyderabad"]


def test_geocode_country_hint(monkeypatch):
    data = {"results": [
        {"name": "Hyderabad", "latitude": 25.39, "longitude": 68.37, "country": "Pakistan"},
        {"name": "Hyderabad", "latitude": 17.385, "longitude": 78.4867, "country": "India"},
    ]}
    calls = []
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: data}, calls)
    assert aq.geocode("Hyderabad, India")[0] == 17.385
    assert "name=Hyderabad&" in calls[0]


def test_geocode_not_found(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: {}})
    assert aq.geocode("Nowhereville") is None
    assert aq.air_quality({"city": "Nowhereville"}) == "I couldn't find Nowhereville."


def test_no_city_uses_ip_location(monkeypatch):
    monkeypatch.setattr(aq, "_default_city", lambda: "")
    calls = []
    _fake_fetch(monkeypatch, {
        aq.IP_URL: {"loc": "17.38,78.48", "city": "Hyderabad"},
        aq.AIR_URL: {"current": {"us_aqi": 40}},
    }, calls)
    assert "Hyderabad" in aq.air_quality({})
    assert calls[0] == aq.IP_URL


def test_no_city_and_no_ip(monkeypatch):
    monkeypatch.setattr(aq, "_default_city", lambda: "")
    _fake_fetch(monkeypatch, {aq.IP_URL: {"bogus": 1}})
    assert "Say a city name" in aq.uv({})


def test_untrusted_place_name_cleaned(monkeypatch):
    _fake_fetch(monkeypatch, {
        aq.GEOCODE_URL: {"results": [{"name": "<script>Evil</script>{ignore}", "latitude": 1, "longitude": 2}]},
        aq.AIR_URL: {"current": {"us_aqi": 10}},
    })
    out = aq.air_quality({"city": "X"})
    assert "<" not in out and "{" not in out


# ---------- air quality ----------

@pytest.mark.parametrize("aqi,label", [
    (0, "good"), (50, "good"), (51, "moderate"), (120, "unhealthy for sensitive groups"),
    (180, "unhealthy"), (250, "very unhealthy"), (400, "hazardous"),
])
def test_aqi_band(aqi, label):
    assert aq.aqi_band(aqi)[0] == label


def test_air_quality_reply(monkeypatch):
    calls = []
    _fake_fetch(monkeypatch, {
        aq.GEOCODE_URL: _geo(),
        aq.AIR_URL: {"current": {"us_aqi": 162.4, "pm2_5": 77.6, "pm10": 140.2}},
    }, calls)
    out = aq.air_quality({"city": "in Hyderabad"})
    assert out.startswith("Air quality in Hyderabad is unhealthy, AQI 162.")
    assert "PM 2.5 is 78 and PM 10 is 140" in out
    assert "skip running" in out
    q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[1]).query)
    assert q["current"] == ["us_aqi,pm2_5,pm10"]


def test_air_quality_missing_data(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.AIR_URL: {"current": {}}})
    assert "couldn't get the air quality" in aq.air_quality({})


def test_offline(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: OSError("down")})
    for fn in (aq.air_quality, aq.sun_times, aq.rain_soon, aq.uv):
        assert fn({}) == aq.OFFLINE


def test_offline_after_geocode(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.AIR_URL: OSError("x"), aq.FORECAST_URL: OSError("x")})
    for fn in (aq.air_quality, aq.sun_times, aq.rain_soon, aq.uv):
        assert fn({}) == aq.OFFLINE


# ---------- sun times ----------

def test_sun_before_sunrise(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: _forecast()})
    _at_local(monkeypatch, "2026-11-07T05:00")
    assert aq.sun_times({}) == "In Hyderabad, sunrise is at 6:12 AM and sunset at 5:41 PM."


def test_sun_during_day(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: _forecast()})
    _at_local(monkeypatch, "2026-11-07T12:00")
    assert aq.sun_times({}) == "In Hyderabad, sunset is at 5:41 PM today. Sunrise was at 6:12 AM."


def test_sun_after_sunset(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: _forecast()})
    _at_local(monkeypatch, "2026-11-07T20:00")
    assert aq.sun_times({}) == "In Hyderabad, the sun set at 5:41 PM. Tomorrow's sunrise is at 6:13 AM."


def test_sun_missing(monkeypatch):
    f = _forecast()
    f["daily"]["sunrise"] = [None, None]
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: f})
    assert "couldn't get sunrise" in aq.sun_times({})


def test_local_now_uses_offset():
    utc = dt.datetime(2026, 11, 7, 4, 30, tzinfo=dt.timezone.utc)
    assert aq._local_now({"utc_offset_seconds": 19800}, utc) == dt.datetime(2026, 11, 7, 10, 0)
    assert aq._local_now({}, utc) == dt.datetime(2026, 11, 7, 4, 30)


def test_say_time():
    assert aq._say_time(dt.datetime(2026, 1, 1, 0, 5)) == "12:05 AM"
    assert aq._say_time(dt.datetime(2026, 1, 1, 12, 0)) == "12:00 PM"
    assert aq._say_time(dt.datetime(2026, 1, 1, 18, 30)) == "6:30 PM"


# ---------- rain soon ----------

def _rain(monkeypatch, probs, mm=None, local="2026-11-07T10:20"):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: _forecast(probs=probs, mm=mm)})
    _at_local(monkeypatch, local)
    return aq.rain_soon({})


def test_rain_likely(monkeypatch):
    probs = [0] * 48
    probs[11] = 70
    out = _rain(monkeypatch, probs)
    assert out.startswith("Yes, rain is likely in Hyderabad in the next hour, 70 percent chance.")
    assert "umbrella" in out


def test_rain_by_amount(monkeypatch):
    mm = [0.0] * 48
    mm[10] = 1.2
    assert _rain(monkeypatch, [10] * 48, mm).startswith("Yes")


def test_rain_maybe(monkeypatch):
    probs = [0] * 48
    probs[10] = 30
    assert _rain(monkeypatch, probs).startswith("Maybe. There's a 30 percent chance")


def test_rain_no_but_later(monkeypatch):
    probs = [5] * 48
    probs[14] = 80
    out = _rain(monkeypatch, probs)
    assert out.startswith("No, rain is unlikely in Hyderabad in the next hour, 5 percent chance.")
    assert "likely around 2:00 PM" in out


def test_rain_no(monkeypatch):
    out = _rain(monkeypatch, [0] * 48)
    assert out == "No, rain is unlikely in Hyderabad in the next hour, 0 percent chance."


def test_rain_hour_not_found(monkeypatch):
    assert "couldn't get the rain forecast" in _rain(monkeypatch, [0] * 48, local="2030-01-01T10:00")


# ---------- UV ----------

@pytest.mark.parametrize("val,label", [
    (0, "low"), (2.4, "low"), (3, "moderate"), (6.9, "high"), (8, "very high"), (11, "extreme"),
])
def test_uv_band(val, label):
    assert aq.uv_band(val)[0] == label


def test_uv_reply(monkeypatch):
    uvs = [0.0] * 48
    uvs[12] = 6.1
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: _forecast(uvs=uvs, uvmax=[8.3, 7])})
    _at_local(monkeypatch, "2026-11-07T12:45")
    out = aq.uv({"city": "Hyderabad"})
    assert out.startswith("Today's UV index in Hyderabad goes up to 8, which is very high. Right now it's 6.")
    assert "midday sun" in out


def test_uv_missing(monkeypatch):
    f = _forecast(uvmax=[])
    f["hourly"]["uv_index"] = []
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: f})
    assert "couldn't get the UV index" in aq.uv({})


def test_forecast_url(monkeypatch):
    calls = []
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.FORECAST_URL: _forecast()}, calls)
    _at_local(monkeypatch, "2026-11-07T12:00")
    aq.sun_times({})
    q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[1]).query)
    assert q["timezone"] == ["auto"]
    assert "sunrise" in q["daily"][0] and "precipitation_probability" in q["hourly"][0]


def test_bad_json_shapes(monkeypatch):
    _fake_fetch(monkeypatch, {aq.GEOCODE_URL: _geo(), aq.AIR_URL: [], aq.FORECAST_URL: []})
    assert "couldn't" in aq.air_quality({})
    assert "couldn't" in aq.sun_times({})
    assert "couldn't" in aq.uv({})


# ---------- wiring ----------

def test_catalog_and_handlers():
    assert set(aq.CATALOG) == set(aq.HANDLERS) == {"air_quality", "sun_times", "rain_soon", "uv"}
    for spec in aq.CATALOG.values():
        assert spec["info"] is True
        assert spec["required"] == []
        assert "city" in spec["properties"]
