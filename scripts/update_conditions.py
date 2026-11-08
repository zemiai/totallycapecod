"""Update data/conditions.json — tides, sun, weather, 7-day forecast.

Sources (all free, no auth):
- NOAA Tides & Currents: api.tidesandcurrents.noaa.gov (Chatham station 8447435)
- weather.gov: api.weather.gov (point 41.78,-70.03 ~= mid-Cape)
- sunrise-sunset.org: api.sunrise-sunset.org

Runs daily at 4 AM ET via update-conditions.yml.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import safe_write

OUT = Path(__file__).parent.parent / "data" / "conditions.json"

# Mid-Cape reference point used for sun + weather
LAT, LNG = 41.78, -70.03
NOAA_STATION = "8447435"  # Chatham, MA — tides + water temp


def fetch_tides(date: str) -> list[dict]:
    """NOAA tide predictions for a given YYYYMMDD date."""
    r = requests.get(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
        params={
            "begin_date": date,
            "end_date": date,
            "station": NOAA_STATION,
            "product": "predictions",
            "datum": "MLLW",
            "units": "english",
            "time_zone": "lst_ldt",
            "interval": "hilo",
            "format": "json",
        },
        timeout=20,
    )
    r.raise_for_status()
    preds = r.json().get("predictions", [])
    out = []
    for p in preds:
        dt = datetime.fromisoformat(p["t"])
        out.append({
            "time": dt.strftime("%-I:%M %p") if sys.platform != "win32" else dt.strftime("%I:%M %p").lstrip("0"),
            "type": "high" if p["type"] == "H" else "low",
            "height_ft": round(float(p["v"]), 1),
        })
    return out


WATER_BUOY = ("44090", "Cape Cod Bay buoy (NDBC 44090)")   # same sensor the app's beach list uses


def fetch_water_temp() -> int | None:
    """Latest Cape Cod Bay buoy water temperature (NDBC 44090), °F. None if unavailable.

    The Chatham tide station (8447435) has no water-temperature sensor, so the old lookup
    always failed and the page showed a fixed fallback of 64°F. Never substitute a number.
    """
    try:
        r = requests.get(f"https://www.ndbc.noaa.gov/data/realtime2/{WATER_BUOY[0]}.txt", timeout=20,
                         headers={"User-Agent": "TotallyCapeCod/1.0 (+https://totallycapecod.com)"})
        r.raise_for_status()
        lines = [l for l in r.text.splitlines() if l.strip()]
        header = lines[0].lstrip("#").split()
        wi = header.index("WTMP")
        for row in lines[2:]:                      # skip header + units rows; newest first
            cols = row.split()
            if len(cols) > wi and cols[wi] not in ("MM", "999.0", "99.0", "999"):
                return round(float(cols[wi]) * 9 / 5 + 32)
    except Exception as e:
        print(f"[hermes] water_temp lookup failed: {e}", file=sys.stderr)
    return None


def fetch_sun(date: str) -> dict:
    """Sunrise + sunset for the given YYYY-MM-DD date."""
    r = requests.get(
        "https://api.sunrise-sunset.org/json",
        params={"lat": LAT, "lng": LNG, "date": date, "formatted": 0},
        timeout=20,
    )
    r.raise_for_status()
    res = r.json()["results"]
    # Convert UTC ISO timestamps to Eastern time strings
    def fmt(iso_utc: str) -> str:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        # Real America/New_York conversion (the old fixed -4h was an hour off all winter).
        dt_local = dt.astimezone(ZoneInfo("America/New_York"))
        return dt_local.strftime("%I:%M %p").lstrip("0")
    return {
        "sunrise": fmt(res["sunrise"]),
        "sunset": fmt(res["sunset"]),
        "civil_twilight_end": fmt(res["civil_twilight_end"]),
    }


def fetch_weather() -> dict:
    """7-day forecast via weather.gov (free, no key)."""
    point = requests.get(f"https://api.weather.gov/points/{LAT},{LNG}",
                        headers={"User-Agent": "totallycapecod/1.0"}, timeout=20)
    point.raise_for_status()
    forecast_url = point.json()["properties"]["forecast"]

    fc = requests.get(forecast_url, headers={"User-Agent": "totallycapecod/1.0"}, timeout=20)
    fc.raise_for_status()
    periods = fc.json()["properties"]["periods"]

    # Map weather.gov shortForecast to emoji + condition
    def icon_for(short: str) -> tuple[str, str]:
        s = short.lower()
        if "thunder" in s: return ("⛈️", "Storms")
        if "rain" in s or "shower" in s: return ("🌧️", "Rain")
        if "snow" in s: return ("❄️", "Snow")
        if "fog" in s: return ("🌫️", "Fog")
        if "cloud" in s and "partly" in s: return ("⛅", "Partly cloudy")
        if "cloud" in s: return ("☁️", "Cloudy")
        if "sun" in s or "clear" in s: return ("☀️", "Sunny")
        return ("🌤️", short.title())

    # weather.gov returns alternating day/night periods. Group by date.
    today_period = next((p for p in periods if p["isDaytime"]), periods[0])
    icon, cond = icon_for(today_period["shortForecast"])
    today_weather = {
        "temp_high": today_period["temperature"],
        "temp_low": None,  # filled from the paired night period below; never estimated
        "condition": cond,
        "icon": icon,
        "wind_mph": int(today_period.get("windSpeed", "0").split()[0] or 0),
        "wind_dir": today_period.get("windDirection", ""),
    }
    # Pair night period for low
    night_today = next((p for p in periods if not p["isDaytime"] and p["startTime"][:10] == today_period["startTime"][:10]), None)
    if night_today:
        today_weather["temp_low"] = night_today["temperature"]

    # 7-day rollup
    by_date: dict[str, dict] = {}
    for p in periods:
        d = p["startTime"][:10]
        slot = by_date.setdefault(d, {"date": d, "day": datetime.fromisoformat(d).strftime("%a")})
        if p["isDaytime"]:
            i, c = icon_for(p["shortForecast"])
            slot["temp_high"] = p["temperature"]
            slot["condition"] = c
            slot["icon"] = i
        else:
            slot["temp_low"] = p["temperature"]
    forecast_7day = [v for v in list(by_date.values())[:7] if "temp_high" in v]

    return today_weather, forecast_7day


def main() -> None:
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_noaa = today_date.replace("-", "")

    today_weather, forecast_7day = fetch_weather()
    sun = fetch_sun(today_date)
    tides = fetch_tides(today_noaa)
    water_temp = fetch_water_temp()

    # Decorate forecast with sun + tide for each day
    for day in forecast_7day:
        day_noaa = day["date"].replace("-", "")
        try:
            day_sun = fetch_sun(day["date"])
            day["sunrise"] = day_sun["sunrise"]
            day["sunset"] = day_sun["sunset"]
        except Exception:
            pass
        try:
            day_tides = fetch_tides(day_noaa)
            lows = [t for t in day_tides if t["type"] == "low"]
            highs = [t for t in day_tides if t["type"] == "high"]
            if lows: day["low_tide"] = lows[0]["time"]
            if highs: day["high_tide"] = highs[0]["time"]
        except Exception:
            pass

    payload = {
        "today": {
            "date": today_date,
            "weather": today_weather,
            # Only measured/forecast values with a named source go here. (A fixed "best sunset
            # spot" and a placeholder swell of 2 ft @ 8 s were removed on Nov 8, 2026: they
            # weren't measurements, and the site only passes along verifiable data.)
            "sun": {**sun, "source": "sunrise-sunset.org"},
            "tides": tides,
            "tides_source": f"NOAA Tides & Currents, Chatham station {NOAA_STATION}",
            "water_temp_f": water_temp,
            "water_temp_source": WATER_BUOY[1] if water_temp is not None else None,
            "weather_source": "National Weather Service (api.weather.gov)",
        },
        "forecast_7day": forecast_7day,
    }

    safe_write(OUT, payload, count_key=None, min_ratio=0.5)


if __name__ == "__main__":
    main()
