import pytest
import services.weather_service as weather_module

SAMPLE = {
    "coord": {"lon": 4.9, "lat": 51.5},
    "weather": [{"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"}],
    "main": {"temp": 20.0, "feels_like": 19.0, "temp_min": 18.0, "temp_max": 22.0, "pressure": 1013, "humidity": 60},
    "wind": {"speed": 3.0, "deg": 180, "gust": 5.0},
    "name": "TestCity",
    "cod": 200,
}


@pytest.fixture
def with_weather(monkeypatch):
    monkeypatch.setitem(weather_module.WEATHER_DATA, "data", SAMPLE)
    monkeypatch.setitem(weather_module.WEATHER_DATA, "last_updated", "2026-01-01T00:00:00")


@pytest.fixture
def no_weather(monkeypatch):
    monkeypatch.setitem(weather_module.WEATHER_DATA, "data", None)
    monkeypatch.setitem(weather_module.WEATHER_DATA, "last_updated", 0)


async def test_weather_returns_data(client, with_weather):
    response = await client.get("/weather")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["name"] == "TestCity"
    assert body["data"]["main"]["temp"] == 20.0
    assert body["data"]["wind"]["speed"] == 3.0
    assert body["last_updated"] == "2026-01-01T00:00:00"


async def test_weather_shape(client, with_weather):
    body = (await client.get("/weather")).json()
    assert "coord" in body["data"]
    assert "weather" in body["data"]
    assert "main" in body["data"]
    assert "wind" in body["data"]


async def test_weather_no_data_returns_null(client, no_weather):
    response = await client.get("/weather")
    assert response.status_code == 200
    assert response.json()["data"] is None
