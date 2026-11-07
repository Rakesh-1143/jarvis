"""Internet skills that use free APIs with no API key."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from .. import net
from . import skill

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "a thunderstorm", 96: "a thunderstorm with hail",
    99: "a thunderstorm with hail",
}


@skill("get_weather", "Get the current weather and today's forecast for a city.",
       patterns=[r"(what('s| is) the |how('s| is) the )?weather( like)?( today| now)?( in (?P<city>[a-z .'-]+?))?( today| now)?",
                 r"(is it|will it) (going to )?rain( today)?( in (?P<city>[a-z .'-]+))?",
                 r"(what('s| is) the )?temperature( in (?P<city>[a-z .'-]+))?"],
       params={"city": "City name, e.g. 'London'"})
def get_weather(ctx, city: str = ""):
    city = city or ctx.config["weather"]["city"]
    if not city:
        return "Which city? You can also set a default city in config.toml."
    geo = net.get_json("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1})
    if not geo.get("results"):
        return f"I couldn't find a place called {city}."
    place = geo["results"][0]
    data = net.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 1,
    })
    cur, day = data["current"], data["daily"]
    desc = WEATHER_CODES.get(cur["weather_code"], "unknown conditions")
    rain = day.get("precipitation_probability_max", [None])[0]
    rain_txt = f" Chance of rain is {rain} percent." if rain is not None else ""
    return (
        f"In {place['name']} it's {round(cur['temperature_2m'])} degrees with {desc}, "
        f"feels like {round(cur['apparent_temperature'])}. Humidity {cur['relative_humidity_2m']} percent, "
        f"wind {round(cur['wind_speed_10m'])} km/h. Today's high is {round(day['temperature_2m_max'][0])} "
        f"and low is {round(day['temperature_2m_min'][0])}.{rain_txt}"
    )


@skill("wikipedia", "Get a short Wikipedia summary about a person, place or topic.",
       patterns=[r"(search )?wikipedia (for |about )?(?P<topic>.+)", r"(who|what) (is|was|are|were) (?P<topic>.+?) (on|according to) wikipedia",
                 r"tell me about (?P<topic>.+)"],
       params={"topic": "The topic to look up"}, required=["topic"])
def wikipedia(ctx, topic: str):
    if topic.lower() in ("yourself", "you", "jarvis"):
        return "I'm Jarvis, your free personal assistant. I run on your computer and use open-source AI."
    found = net.get_json("https://en.wikipedia.org/w/api.php", {
        "action": "opensearch", "search": topic, "limit": 1, "namespace": 0, "format": "json"})
    if not found or not found[1]:
        return f"I found nothing on Wikipedia about {topic}."
    title = found[1][0]
    data = net.get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + net.urllib.parse.quote(title.replace(" ", "_")))
    text = data.get("extract", "")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:3]) or f"Wikipedia has a page on {title}, but no summary."


@skill("web_search", "Search the internet and return a short answer with top results.",
       patterns=[r"(search( the web| the internet| online)?|google|look up) (for )?(?P<query>.+)"],
       params={"query": "What to search for"}, required=["query"])
def web_search(ctx, query: str):
    # 1) DuckDuckGo instant answers (free, no key).
    try:
        ia = net.get_json("https://api.duckduckgo.com/", {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
        answer = ia.get("Answer") or ia.get("AbstractText") or ia.get("Definition")
        if answer:
            return str(answer)
    except Exception:
        pass
    # 2) DuckDuckGo HTML results page.
    page = net.get("https://html.duckduckgo.com/html/", {"q": query}).decode("utf-8", "ignore")
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', page, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    clean = lambda s: html.unescape(re.sub(r"<.*?>", "", s)).strip()
    if not titles:
        return f"I couldn't find results for {query}."
    lines = []
    for i, t in enumerate(titles[:3]):
        snip = clean(snippets[i]) if i < len(snippets) else ""
        lines.append(f"{i + 1}. {clean(t)}" + (f": {snip}" if snip else ""))
    return "Here's what I found. " + " ".join(lines)


@skill("get_news", "Read the latest news headlines, optionally about a topic.",
       patterns=[r"(what('s| is) the |read (me )?the |latest |today'?s )?(news|headlines)( today)?( about| on)?( (?P<topic>.+))?"],
       params={"topic": "Optional news topic"})
def get_news(ctx, topic: str = ""):
    if topic:
        url = "https://news.google.com/rss/search?" + net.urllib.parse.urlencode({"q": topic, "hl": "en", "gl": "US", "ceid": "US:en"})
    else:
        url = "https://news.google.com/rss?hl=en&gl=US&ceid=US:en"
    root = ET.fromstring(net.get(url))
    items = [i.findtext("title", "") for i in root.iter("item")][:5]
    if not items:
        return "I couldn't get the news right now."
    return "Top headlines: " + " ... ".join(f"{n + 1}. {t}" for n, t in enumerate(items))
