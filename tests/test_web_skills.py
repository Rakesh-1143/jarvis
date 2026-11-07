from jarvis.skills import web


def test_weather(jarvis, monkeypatch):
    def fake(url, params=None, timeout=10):
        if "geocoding" in url:
            assert params["name"] == "Paris"
            return {"results": [{"name": "Paris", "latitude": 48.85, "longitude": 2.35}]}
        return {"current": {"temperature_2m": 21.4, "apparent_temperature": 20.6, "relative_humidity_2m": 55,
                            "weather_code": 2, "wind_speed_10m": 11.2},
                "daily": {"temperature_2m_max": [24.1], "temperature_2m_min": [14.9],
                          "precipitation_probability_max": [10]}}

    monkeypatch.setattr(web.net, "get_json", fake)
    reply = jarvis.handle("what's the weather in Paris")
    assert reply.startswith("In Paris it's 21 degrees with partly cloudy")
    assert "Chance of rain is 10 percent" in reply


def test_wikipedia(jarvis, monkeypatch):
    def fake(url, params=None, timeout=10):
        if params:
            return ["Tony Stark", ["Tony Stark"], [""], [""]]
        return {"extract": "Tony Stark is a fictional character. He is Iron Man. He is rich. Extra sentence."}

    monkeypatch.setattr(web.net, "get_json", fake)
    assert jarvis.handle("tell me about tony stark") == "Tony Stark is a fictional character. He is Iron Man. He is rich."


def test_news(jarvis, monkeypatch):
    rss = b"<rss><channel><item><title>A</title></item><item><title>B</title></item></channel></rss>"
    monkeypatch.setattr(web.net, "get", lambda *a, **k: rss)
    assert jarvis.handle("what's the news") == "Top headlines: 1. A ... 2. B"


def test_no_internet_message(jarvis, monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(web.net, "get_json", boom)
    assert "can't reach the internet" in jarvis.handle("weather in Paris")
