from fastapi import FastAPI, HTTPException, Request
from cachetools import TTLCache
import httpx
import math
import json, gzip

app = FastAPI(title="Weather API")

# 5 minute cache
cache = TTLCache(maxsize=1000, ttl=300)

WEATHER_CODES = {
    0: ("100", "晴"),
    1: ("101", "晴"),
    2: ("102", "少云"),
    3: ("103", "多云"),
    45: ("501", "雾"),
    48: ("501", "雾"),
    51: ("305", "毛毛雨"),
    53: ("306", "小雨"),
    55: ("307", "中雨"),
    61: ("306", "小雨"),
    63: ("307", "中雨"),
    65: ("308", "大雨"),
    71: ("400", "小雪"),
    73: ("401", "中雪"),
    75: ("402", "大雪"),
    80: ("300", "阵雨"),
    81: ("301", "强阵雨"),
    82: ("302", "暴雨"),
    95: ("302", "雷暴"),
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

@app.middleware("http")
async def log_requests(request, call_next):
    print("REQUEST:", request.method, request.url)
    response = await call_next(request)
    print("RESPONSE:", response.status_code)
    return response

async def get_coordinates(location: str) -> tuple[float, float]:
    print(f"get_coordinates called: {location}")
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
    print(f"city lookup called: {location}")
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

@app.get("/v7/weather/now")
def weather():
    data = {
        "code": "200",
        "updateTime": "2026-06-15T22:00+08:00",
        "now": {
            "obsTime": "2026-06-15T22:00+08:00",
            "temp": 25,
            "feelsLike": 25,
            "icon": "100",
            "text": "Clear",
            "wind360": 180,
            "windDir": "South",
            "windScale": 2,
            "windSpeed": 10,
            "humidity": 60,
            "precip": 0.0,
            "pressure": 1013,
            "vis": 10,
            "cloud": 0,
            "dew": 0
        }
    }

    raw = json.dumps(data).encode("utf-8")
    gz = gzip.compress(raw)

    return Response(
        content=gz,
        media_type="application/json",
        headers={
            "Content-Encoding": "gzip",
            "Connection": "close",
            "Vary": "Accept-Encoding"
        }
    )

@app.get("/v7/old/weather/now")
async def weather_now(
    location: str,
    request: Request,
    key: str = "",
    unit: str = "m",
    lang: str = "zh"
):
    print(
        f"weather now called: "
        f"location={location} "
        f"key={key} "
        f"unit={unit} "
        f"lang={lang}"
    )
    """
    location=52.52,13.41
    """
    print(f"weather now called: {location}")
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
        "fxLink": "https://www.qweather.com",
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
            "dew": "0"
        },
        "refer": {
            "sources": ["Open-Meteo"],
            "license": ["CC BY 4.0"]
        }
    }

    print(json.dumps(response, ensure_ascii=False))
    cache[location] = response

    return response

@app.get("/v7/weather/3d")
async def weather_3d(location: str):
    print(f"weather 3d called: {location}")
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
async def weather_7d(location: str):
    print(f"weather 7d called: {location}")
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
    print(f"air now called: {location}")
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
