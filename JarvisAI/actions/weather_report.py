"""Real-time weather and 5-day Open-Meteo forecast with automatic live location detection."""
from __future__ import annotations

import time
import requests


_WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 66: "Light freezing rain",
    67: "Heavy freezing rain", 71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

_LOCATION_CACHE: dict = {"data": None, "ts": 0.0}


def get_live_location() -> dict:
    """Detect current live location using IP geolocation with caching."""
    now = time.time()
    if _LOCATION_CACHE["data"] and (now - _LOCATION_CACHE["ts"]) < 3600:
        return _LOCATION_CACHE["data"]

    urls = [
        "http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon,timezone",
        "https://ipapi.co/json/",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=4, headers={"User-Agent": "JARVIS/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                if "lat" in data and "lon" in data:
                    loc = {
                        "city": data.get("city") or "Current Location",
                        "region": data.get("regionName") or data.get("region") or "",
                        "country": data.get("country") or data.get("country_name") or "",
                        "lat": float(data["lat"]),
                        "lon": float(data["lon"]),
                        "timezone": data.get("timezone") or "auto",
                    }
                    _LOCATION_CACHE["data"] = loc
                    _LOCATION_CACHE["ts"] = now
                    return loc
                elif "latitude" in data and "longitude" in data:
                    loc = {
                        "city": data.get("city") or "Current Location",
                        "region": data.get("region") or "",
                        "country": data.get("country_name") or "",
                        "lat": float(data["latitude"]),
                        "lon": float(data["longitude"]),
                        "timezone": data.get("timezone") or "auto",
                    }
                    _LOCATION_CACHE["data"] = loc
                    _LOCATION_CACHE["ts"] = now
                    return loc
        except Exception:
            continue

    fallback = {
        "city": "Colombo", "region": "Western Province", "country": "Sri Lanka",
        "lat": 6.9271, "lon": 79.8612, "timezone": "Asia/Colombo"
    }
    return fallback


def _forecast(city: str = "") -> dict:
    headers = {"User-Agent": "JARVIS Desktop Assistant/1.0"}
    clean_city = str(city or "").strip().lower()
    use_live = (not clean_city or clean_city in ("current", "here", "my location", "live", "live location", "local", "auto", "my city"))

    if use_live:
        loc = get_live_location()
        lat, lon = loc["lat"], loc["lon"]
        loc_name = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
        tz = loc.get("timezone") or "auto"
    else:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            headers=headers, timeout=8,
        )
        geo.raise_for_status()
        places = geo.json().get("results") or []
        if not places:
            raise ValueError(f"No matching location found for {city}.")
        place = places[0]
        lat, lon = place["latitude"], place["longitude"]
        loc_name = ", ".join(x for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)
        tz = "auto"

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
            "forecast_days": 5, "timezone": tz,
        },
        headers=headers, timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    current = data.get("current", {})
    daily = data.get("daily", {})

    cur_temp = current.get("temperature_2m", 0)
    cur_feels = current.get("apparent_temperature", cur_temp)
    cur_humidity = current.get("relative_humidity_2m", 0)
    cur_precip = current.get("precipitation", 0.0)
    cur_wind = current.get("wind_speed_10m", 0.0)
    cur_code = current.get("weather_code", 0)
    cur_summary = _WEATHER_CODES.get(cur_code, "Clear")

    days = []
    count = len(daily.get("time", []))
    for i in range(count):
        code = daily.get("weather_code", [None] * count)[i]
        high = daily.get("temperature_2m_max", [None] * count)[i]
        low = daily.get("temperature_2m_min", [None] * count)[i]
        rain = daily.get("precipitation_probability_max", [None] * count)[i]
        wind = daily.get("wind_speed_10m_max", [None] * count)[i]
        extras = []
        if rain is not None:
            extras.append(f"Rain chance {rain}%")
        if wind is not None:
            extras.append(f"Wind up to {wind:g} km/h")
        high_text = f"{high:g}°C" if high is not None else "—"
        low_text = f"{low:g}°C" if low is not None else "—"
        days.append({
            "day": daily.get("time", [""] * count)[i],
            "summary": _WEATHER_CODES.get(code, "Forecast"),
            "detail": f"High {high_text} · low {low_text}" + (" · " + " · ".join(extras) if extras else ""),
        })

    return {
        "location": loc_name,
        "current": {
            "temp": cur_temp,
            "feels_like": cur_feels,
            "humidity": cur_humidity,
            "precip": cur_precip,
            "wind": cur_wind,
            "summary": cur_summary,
        },
        "days": days,
    }


def weather_action(parameters: dict | None = None, player=None, session_memory=None) -> str:
    city = str((parameters or {}).get("city", "")).strip()
    try:
        report = _forecast(city)
        if player and hasattr(player, "show_weather"):
            player.show_weather(report)
        cur = report["current"]
        loc = report["location"]
        days = report["days"]
        today = days[0] if days else {}
        today_detail = today.get("detail", "")

        spoken = (
            f"In {loc}, it is currently {cur['temp']:g}°C (feels like {cur['feels_like']:g}°C) "
            f"with {cur['summary'].lower()}. Humidity is {cur['humidity']}%, wind speed is {cur['wind']:g} km/h. "
            f"{today_detail}."
        )
        return spoken
    except Exception as exc:
        target = city or "your current location"
        return f"I couldn't retrieve the live weather forecast for {target}: {exc}"


TOOL = {
    "name": "weather_report",
    "description": (
        "Fetches accurate real-time weather and 5-day forecast, automatically using "
        "the user's live location if a city is not specified."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "city": {
                "type": "STRING",
                "description": "City and optionally country (e.g. 'Colombo', 'Kandy', 'Tokyo'). Leave blank or pass 'current' to use the user's live location."
            }
        },
        "required": [],
    },
    "handler": weather_action,
}
