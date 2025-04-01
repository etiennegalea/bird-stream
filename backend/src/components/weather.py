import os
import requests
from fastapi import HTTPException
import asyncio
from src.utils import load_api_key


# Weather API configuration
WEATHER_API_KEY = load_api_key('WEATHER_API_KEY')
WEATHER_CACHE = {"data": None, "timestamp": 0}
CACHE_DURATION = 3600  # Cache duration in seconds (1 hour)

async def get_weather():
    """Get weather data for Rotterdam"""
    current_time = asyncio.get_event_loop().time()
    
    # Return cached data if it's still valid
    if WEATHER_CACHE["data"] and (current_time - WEATHER_CACHE["timestamp"]) < CACHE_DURATION:
        return WEATHER_CACHE["data"]
    
    # If no API key is configured, return an error
    if not WEATHER_API_KEY:
        raise HTTPException(status_code=500, detail="Weather API not configured")
    
    try:
        # Make request to OpenWeatherMap API
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "q": "Rotterdam, nl",
                "units": "metric",
                "appid": WEATHER_API_KEY
            }
        )
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Parse the JSON response
        weather_data = response.json()
        
        # Update the cache
        WEATHER_CACHE["data"] = weather_data
        WEATHER_CACHE["timestamp"] = current_time
        
        return weather_data
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Error fetching weather data: {str(e)}")
