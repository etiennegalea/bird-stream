from litestar import get

from services.weather_service import WEATHER_DATA


@get("/weather", tags=["weather"], sync_to_thread=False)
def weather_endpoint() -> dict:
    return {
        "data": WEATHER_DATA["data"],
        "last_updated": WEATHER_DATA["last_updated"],
    }
