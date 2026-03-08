from __future__ import annotations

import logging

import httpx

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.weather_repo import WeatherRepository

logger = logging.getLogger(__name__)

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_CONDITIONS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow",
    77: "snow grains",
    80: "slight showers", 81: "moderate showers", 82: "violent showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


class WeatherService:
    def __init__(self, config: Config, db: Database) -> None:
        self._config = config
        self._db = db

    async def fetch_and_store(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict:
        lat = latitude if latitude is not None else self._config.weather.latitude
        lon = longitude if longitude is not None else self._config.weather.longitude

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "wind_speed_10m",
                "wind_gusts_10m",
                "wind_direction_10m",
                "weather_code",
                "precipitation",
                "snowfall",
                "snow_depth",
                "surface_pressure",
            ]),
            "models": "ecmwf_ifs025",
            "wind_speed_unit": "kmh",
            "timezone": "UTC",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(_OPEN_METEO_URL, params=params, timeout=15.0)
            resp.raise_for_status()

        raw = resp.json()
        current = raw.get("current", {})

        weather_code = current.get("weather_code")
        condition = _WMO_CONDITIONS.get(weather_code, f"code {weather_code}") if weather_code is not None else None

        repo = WeatherRepository(self._db)
        snapshot = await repo.insert(
            latitude=lat,
            longitude=lon,
            temperature=current.get("temperature_2m"),
            apparent_temperature=current.get("apparent_temperature"),
            wind_speed=current.get("wind_speed_10m"),
            wind_gusts=current.get("wind_gusts_10m"),
            wind_direction=current.get("wind_direction_10m"),
            precipitation=current.get("precipitation"),
            snowfall=current.get("snowfall"),
            snow_depth=current.get("snow_depth"),
            surface_pressure=current.get("surface_pressure"),
            condition=condition,
            raw=raw,
        )

        logger.info(
            "Weather: %.1f°C (feels %.1f°C), wind %.1f km/h gusts %.1f km/h from %s°, %s",
            snapshot["temperature"] or 0,
            snapshot["apparent_temperature"] or 0,
            snapshot["wind_speed"] or 0,
            snapshot["wind_gusts"] or 0,
            snapshot["wind_direction"] or 0,
            condition,
        )
        return snapshot
