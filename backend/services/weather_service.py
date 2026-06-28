import asyncio
import logging
from datetime import datetime, timedelta

import requests

from services.config_service import load_api_key

logger = logging.getLogger("weather_service")

WEATHER_API_KEY = load_api_key("WEATHER_API_KEY")
WEATHER_DATA: dict = {"data": None, "last_updated": 0}


class WeatherNotConfiguredError(Exception):
    pass


class WeatherFetchError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def get_weather(lat: float, lon: float, cache_expiration: int) -> None:
    current_time = datetime.now()

    if (
        WEATHER_DATA["data"] is not None
        and WEATHER_DATA["last_updated"] is not None
        and current_time - WEATHER_DATA["last_updated"]
        < timedelta(seconds=cache_expiration)
    ):
        logger.info("Using cached weather data")
        return

    logger.info("Fetching fresh weather data")

    if not WEATHER_API_KEY:
        raise WeatherNotConfiguredError()

    try:
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": lat,
                "lon": lon,
                "units": "metric",
                "appid": WEATHER_API_KEY,
            },
        )
        response.raise_for_status()
        weather_data = response.json()

        if "gemeente" in weather_data["name"].lower():
            weather_data["name"] = weather_data["name"].replace("gemeente ", "")

        WEATHER_DATA["data"] = weather_data
        WEATHER_DATA["last_updated"] = current_time
        WEATHER_DATA["city"] = weather_data["name"]
    except requests.exceptions.RequestException as e:
        raise WeatherFetchError(str(e)) from e


async def fetch_weather_periodically(cache_expiration: int = 3600) -> None:
    ip_info = requests.get("http://ip-api.com/json/").json()
    lat, lon = ip_info["lat"], ip_info["lon"]

    while True:
        try:
            logger.info("Refreshing weather data in background task")
            await get_weather(lat=lat, lon=lon, cache_expiration=cache_expiration)
        except Exception as e:
            logger.error(f"Error refreshing weather data: {e}")

        await asyncio.sleep(cache_expiration)
