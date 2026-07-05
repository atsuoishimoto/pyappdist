"""Open-Meteo weather demo built with NiceGUI.

Pick one of five world cities to see the current conditions, a 24-hour
temperature forecast chart, and the city location on an interactive map.
"""

from __future__ import annotations

import httpx
from nicegui import ui

API_URL = "https://api.open-meteo.com/v1/forecast"

# name -> (latitude, longitude, timezone)
CITIES: dict[str, tuple[float, float, str]] = {
    "Tokyo": (35.6762, 139.6503, "Asia/Tokyo"),
    "New York": (40.7128, -74.0060, "America/New_York"),
    "London": (51.5074, -0.1278, "Europe/London"),
    "Paris": (48.8566, 2.3522, "Europe/Paris"),
    "Sydney": (-33.8688, 151.2093, "Australia/Sydney"),
}

# WMO weather code -> (emoji, label)
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "Clear sky"),
    1: ("🌤️", "Mainly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"),
    45: ("🌫️", "Fog"),
    48: ("🌫️", "Depositing rime fog"),
    51: ("🌦️", "Light drizzle"),
    53: ("🌦️", "Moderate drizzle"),
    55: ("🌦️", "Dense drizzle"),
    61: ("🌧️", "Slight rain"),
    63: ("🌧️", "Moderate rain"),
    65: ("🌧️", "Heavy rain"),
    71: ("🌨️", "Slight snow"),
    73: ("🌨️", "Moderate snow"),
    75: ("🌨️", "Heavy snow"),
    77: ("🌨️", "Snow grains"),
    80: ("🌦️", "Slight rain showers"),
    81: ("🌦️", "Moderate rain showers"),
    82: ("⛈️", "Violent rain showers"),
    85: ("🌨️", "Slight snow showers"),
    86: ("🌨️", "Heavy snow showers"),
    95: ("⛈️", "Thunderstorm"),
    96: ("⛈️", "Thunderstorm with slight hail"),
    99: ("⛈️", "Thunderstorm with heavy hail"),
}


async def fetch_weather(lat: float, lon: float, timezone: str) -> dict:
    """Fetch current conditions and the next 24 hours from Open-Meteo."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "hourly": "temperature_2m",
        "forecast_hours": 24,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(API_URL, params=params)
        response.raise_for_status()
        return response.json()


@ui.page("/")
def index() -> None:
    ui.colors(primary="#3874c8")

    with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
        ui.label("🌍 World Weather").classes("text-3xl font-bold")
        ui.label("Open-Meteo + NiceGUI demo").classes("text-gray-500 -mt-2")

        city_select = ui.select(
            list(CITIES), value="Tokyo", label="City"
        ).classes("w-64")

        # Current-conditions card.
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-6 w-full"):
                icon_label = ui.label().classes("text-6xl")
                with ui.column().classes("gap-0"):
                    temp_label = ui.label().classes("text-4xl font-bold")
                    desc_label = ui.label().classes("text-gray-600")
                ui.space()
                with ui.column().classes("gap-1 text-right"):
                    humidity_label = ui.label().classes("text-gray-600")
                    wind_label = ui.label().classes("text-gray-600")

        with ui.row().classes("w-full gap-4 flex-nowrap"):
            # 24-hour temperature chart.
            with ui.card().classes("flex-1"):
                ui.label("Next 24 hours").classes("font-semibold")
                chart = ui.echart(
                    {
                        "tooltip": {"trigger": "axis"},
                        "xAxis": {"type": "category", "data": []},
                        "yAxis": {"type": "value", "axisLabel": {"formatter": "{value}°"}},
                        "series": [
                            {
                                "type": "line",
                                "data": [],
                                "smooth": True,
                                "areaStyle": {},
                                "name": "Temp",
                            }
                        ],
                        "grid": {"left": 45, "right": 20, "top": 20, "bottom": 30},
                    }
                ).classes("w-full h-64")

            # Map.
            lat, lon, _ = CITIES["Tokyo"]
            leaflet = ui.leaflet(center=(lat, lon), zoom=9).classes("flex-1 h-64")

        async def update(city: str) -> None:
            lat, lon, timezone = CITIES[city]

            # Move the map and drop a single marker.
            leaflet.set_center((lat, lon))
            leaflet.clear_layers()
            leaflet.tile_layer(
                url_template=r"https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                options={"attribution": "© OpenStreetMap"},
            )
            leaflet.marker(latlng=(lat, lon))

            try:
                data = await fetch_weather(lat, lon, timezone)
            except (httpx.HTTPError, KeyError) as exc:
                ui.notify(f"Failed to load weather: {exc}", type="negative")
                return

            current = data["current"]
            code = int(current["weather_code"])
            emoji, label = WEATHER_CODES.get(code, ("❓", "Unknown"))

            icon_label.text = emoji
            temp_label.text = f"{current['temperature_2m']:.0f}°C"
            desc_label.text = label
            humidity_label.text = f"💧 Humidity {current['relative_humidity_2m']}%"
            wind_label.text = f"💨 Wind {current['wind_speed_10m']} km/h"

            hourly = data["hourly"]
            times = [t[11:16] for t in hourly["time"]]  # "HH:MM"
            temps = hourly["temperature_2m"]
            chart.options["xAxis"]["data"] = times
            chart.options["series"][0]["data"] = temps
            chart.update()

        city_select.on_value_change(lambda e: update(e.value))

        # Initial load.
        ui.timer(0.1, lambda: update(city_select.value), once=True)


def main() -> None:
    ui.run(title="World Weather", native=True)


if __name__ in {"__main__", "__mp_main__"}:
    main()
