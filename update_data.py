import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests

# ---- Yahoo Finance top stories (RSS, no key needed) ----
# Runs first and on its own: if Yahoo is down, the old news.json is kept
# and the market data below still updates.
NEWS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://finance.yahoo.com/rss/topstories",
]
MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def fetch_news():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; personal-site-updater)"}
    for url in NEWS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"News feed failed ({url}): {e}")
            continue
        stories = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link.startswith("http"):
                continue
            published = None
            try:
                published = parsedate_to_datetime(item.findtext("pubDate")).astimezone(timezone.utc).isoformat()
            except Exception:
                pass
            image = None
            media = item.find(MEDIA_NS + "content")
            if media is not None and (media.get("url") or "").startswith("http"):
                image = media.get("url")
            stories.append({
                "title": title,
                "link": link,
                "published": published,
                "source": (item.findtext("source") or "").strip() or None,
                "image": image,
            })
        if stories:
            stories.sort(key=lambda s: s["published"] or "", reverse=True)
            return stories[:25]
    return []


stories = fetch_news()
if stories:
    with open("news.json", "w") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "stories": stories}, f)
    print(f"Updated news.json with {len(stories)} stories")
else:
    print("No news fetched, keeping the previous news.json")

FRED_KEY = os.environ["FRED_API_KEY"]

# ---- Bitcoin from CoinGecko (no key needed) ----
price_resp = requests.get(
    "https://api.coingecko.com/api/v3/simple/price",
    params={"ids": "bitcoin", "vs_currencies": "usd", "include_24hr_change": "true"},
    timeout=30,
).json()
btc_price = price_resp["bitcoin"]["usd"]
btc_change = price_resp["bitcoin"]["usd_24h_change"]

hist_resp = requests.get(
    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
    params={"vs_currency": "usd", "days": 90, "interval": "daily"},
    timeout=30,
).json()
btc_history = [
    [datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d"), round(p)]
    for ts, p in hist_resp["prices"]
]

# ---- Yield curve from FRED: T10Y2Y is the 10-year minus 2-year spread ----
fred_resp = requests.get(
    "https://api.stlouisfed.org/fred/series/observations",
    params={
        "series_id": "T10Y2Y",
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "asc",
        "observation_start": "1976-01-01",
    },
    timeout=60,
).json()
obs = [
    [o["date"], float(o["value"])]
    for o in fred_resp["observations"]
    if o["value"] != "."
]
curve_latest = obs[-1][1]

# ---- Simple automatic summary (no AI key required) ----
state = "inverted, which has historically been a recession warning signal" if curve_latest < 0 else "positive, meaning a normal upward-sloping curve"
direction = "up" if btc_change >= 0 else "down"
summary = (
    f"Bitcoin is trading at ${btc_price:,.0f}, {direction} {abs(btc_change):.2f}% over the last 24 hours. "
    f"The 10-year minus 2-year Treasury spread is {curve_latest:.2f}%, which is {state}."
)

data = {
    "updated": datetime.now(timezone.utc).isoformat(),
    "bitcoin": {"price": btc_price, "change_24h": btc_change, "history": btc_history},
    "yield_curve": {"latest": curve_latest, "history": obs},
    "summary": summary,
}

with open("data.json", "w") as f:
    json.dump(data, f)

print("Updated data.json")
