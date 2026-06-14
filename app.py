from fastapi import FastAPI, HTTPException
from cachetools import TTLCache
import httpx
import math

app = FastAPI(title="Weather API")

# 5 minute cache
cache = TTLCache(maxsize=1000, ttl=300)

WEATHER_CODES = {
    0: ("100", "Clear"),
    1: ("101", "Mainly Clear"),
    2: ("102", "Partly Cloudy"),
    3: ("103", "Cloudy"),
    45: ("501", "Fog"),
    48: ("501", "Fog"),
    51: ("305", "Light Drizzle"),
    53: ("306", "Drizzle"),
    55: ("307", "Heavy Drizzle"),
    61: ("306", "Rain"),
    63: ("307", "Rain"),
    65: ("308", "Heavy Rain"),
    71: ("400", "Snow"),
    73: ("401", "Snow"),
    75: ("402", "Heavy Snow"),
    80: ("300", "Rain Shower"),
    81: ("301", "Rain Shower"),
    82: ("302", "Heavy Rain Shower"),
    95: ("302", "Thunderstorm"),
}

DIRECTIONS = [
    "N", "NE", "E", "SE",
    "S", "SW", "W", "NW"
]


def deg_to_dir(deg):
    idx = round(deg / 45) % 8
    return DIRECTIONS[idx]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/weather/now")
async def weather_now(location: str):
    """
    location=52.52,13.41
    """

    if location in cache:
        return cache[location]

    try:
        lat, lon = location.split(",")
        lat = float(lat)
        lon = float(lon)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="location must be lat,lon"
        )

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&current="
        "temperature_2m,"
        "relative_humidity_2m,"
        "apparent_temperature,"
        "precipitation,"
        "surface_pressure,"
        "cloud_cover,"
        "wind_speed_10m,"
        "wind_direction_10m,"
        "weather_code"
        "&timezone=auto"
    )

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="upstream weather provider error"
        )

    data = r.json()
    current = data["current"]

    weather_code = current.get("weather_code", 0)

    icon, text = WEATHER_CODES.get(
        weather_code,
        ("999", "Unknown")
    )

    response = {
        "code": "200",
        "updateTime": current["time"],
        "fxLink": f"https://your-domain.com/weather/{location}",
        "now": {
            "obsTime": current["time"],
            "temp": str(round(current["temperature_2m"])),
            "feelsLike": str(round(current["apparent_temperature"])),
            "icon": icon,
            "text": text,
            "wind360": str(round(current["wind_direction_10m"])),
            "windDir": deg_to_dir(
                current["wind_direction_10m"]
            ),
            "windScale": str(
                max(
                    0,
                    min(
                        12,
                        math.floor(
                            current["wind_speed_10m"] / 5
                        )
                    )
                )
            ),
            "windSpeed": str(
                round(current["wind_speed_10m"])
            ),
            "humidity": str(
                current["relative_humidity_2m"]
            ),
            "precip": str(
                current["precipitation"]
            ),
            "pressure": str(
                round(current["surface_pressure"])
            ),
            "vis": "10",
            "cloud": str(
                current["cloud_cover"]
            ),
            "dew": ""
        },
        "refer": {
            "sources": ["Open-Meteo"]
        }
    }

    cache[location] = response

    return response
