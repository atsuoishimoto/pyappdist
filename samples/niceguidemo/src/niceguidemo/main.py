# app.py
import requests
from nicegui import ui

URL = 'https://api.open-meteo.com/v1/forecast'

CITIES = {
    '東京': {'lat': 35.6895, 'lon': 139.6917, 'tz': 'Asia/Tokyo'},
    'ニューヨーク': {'lat': 40.7128, 'lon': -74.0060, 'tz': 'America/New_York'},
    'ロンドン': {'lat': 51.5072, 'lon': -0.1276, 'tz': 'Europe/London'},
    'パリ': {'lat': 48.8566, 'lon': 2.3522, 'tz': 'Europe/Paris'},
    'シドニー': {'lat': -33.8688, 'lon': 151.2093, 'tz': 'Australia/Sydney'},
}


def fetch_weather(city_name: str):
    city = CITIES[city_name]

    response = requests.get(
        URL,
        params={
            'latitude': city['lat'],
            'longitude': city['lon'],
            'current': (
                'temperature_2m,relative_humidity_2m,'
                'apparent_temperature,weather_code,wind_speed_10m'
            ),
            'daily': (
                'temperature_2m_max,temperature_2m_min,'
                'precipitation_probability_max'
            ),
            'timezone': city['tz'],
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def weather_text(code: int) -> str:
    return {
        0: '快晴',
        1: '晴れ',
        2: '一部曇り',
        3: '曇り',
        45: '霧',
        48: '霧氷',
        51: '弱い霧雨',
        53: '霧雨',
        55: '強い霧雨',
        61: '弱い雨',
        63: '雨',
        65: '強い雨',
        71: '弱い雪',
        73: '雪',
        75: '強い雪',
        80: '弱いにわか雨',
        81: 'にわか雨',
        82: '強いにわか雨',
        95: '雷雨',
    }.get(code, f'不明: {code}')


def metric_card(title: str, value: str):
    with ui.card().classes('w-40 p-4 items-center'):
        ui.label(title).classes('text-sm text-gray-500')
        ui.label(value).classes('text-2xl font-bold')


def update():
    selected_city = city_select.value
    weather_area.clear()

    try:
        data = fetch_weather(selected_city)
        current = data['current']
        daily = data['daily']

        with weather_area:
            ui.label(f'{selected_city} の天気').classes('text-3xl font-bold')
            ui.label(weather_text(current['weather_code'])).classes(
                'text-xl text-gray-600'
            )

            with ui.row().classes('gap-4'):
                metric_card('現在気温', f'{current["temperature_2m"]} ℃')
                metric_card('体感温度', f'{current["apparent_temperature"]} ℃')
                metric_card('湿度', f'{current["relative_humidity_2m"]} %')
                metric_card('風速', f'{current["wind_speed_10m"]} km/h')

            ui.separator()

            ui.label('週間予報').classes('text-2xl font-bold')

            rows = []
            for i, date in enumerate(daily['time']):
                rows.append({
                    'date': date,
                    'max': f'{daily["temperature_2m_max"][i]} ℃',
                    'min': f'{daily["temperature_2m_min"][i]} ℃',
                    'rain': f'{daily["precipitation_probability_max"][i]} %',
                })

            ui.table(
                columns=[
                    {'name': 'date', 'label': '日付', 'field': 'date'},
                    {'name': 'max', 'label': '最高気温', 'field': 'max'},
                    {'name': 'min', 'label': '最低気温', 'field': 'min'},
                    {'name': 'rain', 'label': '降水確率', 'field': 'rain'},
                ],
                rows=rows,
            ).classes('w-full')

    except Exception as e:
        with weather_area:
            ui.label('天気データの取得に失敗しました').classes(
                'text-xl text-red-600'
            )
            ui.label(str(e))

ui.query('body').classes('bg-gray-100')
with ui.column().classes('max-w-4xl mx-auto p-8 gap-6'):
    ui.label('Open-Meteo Dashboard').classes('text-4xl font-bold')

    with ui.card().classes('w-full p-6'):
        with ui.row().classes('w-full items-end gap-4'):
            city_select = ui.select(
                options=list(CITIES.keys()),
                value='東京',
                label='都市を選択',
                on_change=lambda _: update(),
            ).classes('w-64')

            ui.button('更新', on_click=update)

    weather_area = ui.column().classes('w-full gap-4')

    update()

ui.run(native=True)
