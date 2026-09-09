import logging

import requests

from config import YOUTUBE_API_KEY

logger = logging.getLogger(__name__)


def search_youtube(query: str) -> tuple[str | None, str]:
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": 1,
        "key": YOUTUBE_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if response.status_code != 200:
            return None, f"YouTube search failed: {data.get('error', {}).get('message', 'unknown error')}"

        items = data.get("items", [])
        if not items:
            return None, "No results found."

        video_id = items[0]["id"]["videoId"]
        title = items[0]["snippet"]["title"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        return video_url, title

    except Exception as e:
        logger.error("YouTube search error: %s", e)
        return None, f"YouTube search error: {e}"
