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


async def get_weather(cache_expiration):
    """Get weather data for the server's current location"""
    current_time = datetime.now()

    if (WEATHER_DATA["data"] is not None and
        WEATHER_DATA["last_updated"] is not None and
        current_time - WEATHER_DATA["last_updated"] < timedelta(seconds=cache_expiration)):
    
        logger.info("Using cached weather data")
        return WEATHER_DATA["data"]
    
    else:    
        logger.info("Fetching fresh weather data")
    
        # If no API key is configured, return an error
        if not WEATHER_API_KEY:
            raise HTTPException(status_code=500, detail="Weather API not configured")
    
        try:
            # Make request to OpenWeatherMap API using IP-based location detection
            response = await requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "units": "metric",
                    "appid": WEATHER_API_KEY
                }
            )
            
            # Check if the request was successful
            response.raise_for_status()
            
            # Parse the JSON response
            weather_data = response.json()
            
            # Update the cache
            WEATHER_DATA["data"] = weather_data
            WEATHER_DATA["last_updated"] = current_time
            WEATHER_DATA["city"] = weather_data["name"]
        
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=503, detail=f"Error fetching weather data: {str(e)}")


def get_cached_weather():
    """Get the currently cached weather data without making API calls"""
    return WEATHER_DATA["data"]


async def fetch_weather_periodically(cache_expiration=3600):
    """Background task to refresh weather data periodically"""
    while True:
        try:
            logger.info("Refreshing weather data in background task")
            await get_weather(cache_expiration=cache_expiration)
        except Exception as e:
            logger.error(f"Error refreshing weather data: {e}")
        
        # Wait for 1 hour before refreshing again
        await asyncio.sleep(cache_expiration)