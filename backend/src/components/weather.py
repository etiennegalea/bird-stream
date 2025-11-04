import os
import requests
from fastapi import HTTPException
import asyncio
from src.utils import load_api_key
import logging
from datetime import datetime, timedelta


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | weather")


# Weather API configuration
WEATHER_API_KEY = load_api_key('WEATHER_API_KEY')
WEATHER_DATA = {"data": None, "last_updated": 0}


async def get_weather(lat, lon, cache_expiration):
    """Get weather data for Rotterdam"""
    current_time = datetime.now()

    if (WEATHER_DATA["data"] is not None and
        WEATHER_DATA["last_updated"] is not None and
        current_time - WEATHER_DATA["last_updated"] < timedelta(seconds=cache_expiration)):
    
        logger.info("Using cached weather data")
    
    else:    
        logger.info("Fetching fresh weather data")
    
        # If no API key is configured, return an error
        if not WEATHER_API_KEY:
            raise HTTPException(status_code=500, detail="Weather API not configured")
    
        try:
            # Make request to OpenWeatherMap API
            response = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "units": "metric",
                    "appid": WEATHER_API_KEY
                }
            )
            
            # Check if the request was successful
            response.raise_for_status()
            
            # Parse the JSON response
            weather_data = response.json()

            if "gemeente" in weather_data["name"].lower():
                weather_data["name"] = weather_data["name"].replace("gemeente ", "")
            print(weather_data["name"])

            # Update the cache
            WEATHER_DATA["data"] = weather_data
            WEATHER_DATA["last_updated"] = current_time
            WEATHER_DATA["city"] = weather_data["name"]
        
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=503, detail=f"Error fetching weather data: {str(e)}")

async def fetch_weather_periodically(cache_expiration=3600):
    """Background task to refresh weather data periodically"""

    # Get current location
    ip_info = requests.get("http://ip-api.com/json/").json()
    lat, lon = ip_info["lat"], ip_info["lon"]

    while True:
        try:
            logger.info("Refreshing weather data in background task")
            await get_weather(lat=lat, lon=lon, cache_expiration=cache_expiration)
        except Exception as e:
            logger.error(f"Error refreshing weather data: {e}")
        
        # Wait for 1 hour before refreshing again
        await asyncio.sleep(cache_expiration)