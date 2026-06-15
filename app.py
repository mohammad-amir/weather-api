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

async def get_coordinates(location: str) -> tuple[float, float]:
    """
    Accepts:
        52.52,13.41
        Berlin
        London
        Tokyo

    Returns:
        (latitude, longitude)
    """

    # Coordinates already supplied
    if "," in location:
        try:
            lat, lon = location.split(",", 1)
            return float(lat), float(lon)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid coordinates"
            )

    # City lookup
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={location}"
        "&count=1"
        "&language=en"
        "&format=json"
    )

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Geocoding provider unavailable"
        )

    data = r.json()

    results = data.get("results")

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Location '{location}' not found"
        )

    result = results[0]

    return (
        float(result["latitude"]),
        float(result["longitude"])
    )

@app.get("/geo/v2/city/lookup")
async def city_lookup(location: str):

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={location}&count=10&language=en&format=json"
    )

    async with httpx.AsyncClient() as client:
        r = await client.get(url)

    data = r.json()

    locations = []

    for item in data.get("results", []):
        locations.append({
            "name": item["name"],
            "id": str(item["id"]),
            "lat": str(item["latitude"]),
            "lon": str(item["longitude"]),
            "adm2": item.get("admin2", ""),
            "adm1": item.get("admin1", ""),
            "country": item.get("country", "")
        })

    return {
        "code": "200",
        "location": locations
    }


@app.get("/v1/weather/now")
async def weather_now(location: str):
    """
    location=52.52,13.41
    """

    if location in cache:
        return cache[location]

    try:
        lat, lon = await get_coordinates(location)
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

@app.get("/v7/weather/3d")
async def weather_3d(location: str):

    lat, lon = await get_coordinates(location)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily="
        "weather_code,"
        "temperature_2m_max,"
        "temperature_2m_min,"
        "precipitation_probability_max,"
        "wind_speed_10m_max"
        "&forecast_days=3"
    )

    async with httpx.AsyncClient() as client:
        data = (await client.get(url)).json()

    daily = []

    for i in range(3):
        daily.append({
            "fxDate": data["daily"]["time"][i],
            "tempMax": str(data["daily"]["temperature_2m_max"][i]),
            "tempMin": str(data["daily"]["temperature_2m_min"][i]),
            "humidity": "",
            "precip": str(
                data["daily"]["precipitation_probability_max"][i]
            )
        })

    return {
        "code": "200",
        "daily": daily
    }

@app.get("/v7/weather/7d")
async def weather_3d(location: str):

    lat, lon = await get_coordinates(location)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily="
        "weather_code,"
        "temperature_2m_max,"
        "temperature_2m_min,"
        "precipitation_probability_max,"
        "wind_speed_10m_max"
        "&forecast_days=7"
    )

    async with httpx.AsyncClient() as client:
        data = (await client.get(url)).json()

    daily = []

    for i in range(7):
        daily.append({
            "fxDate": data["daily"]["time"][i],
            "tempMax": str(data["daily"]["temperature_2m_max"][i]),
            "tempMin": str(data["daily"]["temperature_2m_min"][i]),
            "humidity": "",
            "precip": str(
                data["daily"]["precipitation_probability_max"][i]
            )
        })

    return {
        "code": "200",
        "daily": daily
    }

@app.get("/v7/air/now")
async def air_now(location: str):

    lat, lon = await get_coordinates(location)

    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&current="
        "pm10,pm2_5,carbon_monoxide,"
        "nitrogen_dioxide,ozone,"
        "sulphur_dioxide,us_aqi"
    )

    async with httpx.AsyncClient() as client:
        data = (await client.get(url)).json()

    current = data["current"]

    return {
        "code": "200",
        "now": {
            "aqi": str(current.get("us_aqi", "")),
            "pm2p5": str(current.get("pm2_5", "")),
            "pm10": str(current.get("pm10", "")),
            "no2": str(current.get("nitrogen_dioxide", "")),
            "so2": str(current.get("sulphur_dioxide", "")),
            "co": str(current.get("carbon_monoxide", "")),
            "o3": str(current.get("ozone", ""))
        }
    }
