import logging
from datetime import datetime

import requests

from config import OPENWEATHER_API_KEY

logger = logging.getLogger(__name__)

DEFAULT_CITY = "Muvattupuzha"


def get_datetime_info() -> str:
    now = datetime.now()
    formatted = now.strftime("%A, %B %d, %Y, %I:%M %p")
    return f"It's currently {formatted}"


def get_time_based_greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning!"
    if hour < 17:
        return "Good afternoon!"
    return "Good evening!"


def get_weather(city: str = DEFAULT_CITY) -> str:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if response.status_code != 200:
            return f"I couldn't get the weather. {data.get('message', 'Unknown error')}"
        temp = data["main"]["temp"]
        description = data["weather"][0]["description"]
        return f"It's currently {temp}°C with {description} in {city}."

    except Exception as e:
        logger.error("Weather fetch failed: %s", e)
        return f"I couldn't fetch the weather right now. Error: {e}"
