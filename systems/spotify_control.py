import logging

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config import SPOTIFY_CACHE_PATH, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI

logger = logging.getLogger(__name__)

SCOPE = "user-modify-playback-state user-read-playback-state"

try:
    sp: spotipy.Spotify | None = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPE,
        cache_path=str(SPOTIFY_CACHE_PATH)
    ))
except Exception:
    logger.exception("Spotify auth setup failed")
    sp = None


def play_on_spotify(query: str) -> str:
    if sp is None:
        return "Spotify isn't set up correctly right now."

    try:
        devices = sp.devices()
        if not devices["devices"]:
            return "I couldn't find an active Spotify device. Please open Spotify on a device first."

        device_id = devices["devices"][0]["id"]

        results = sp.search(q=query, type="track", limit=1, market="IN")
        tracks = results["tracks"]["items"]

        if not tracks:
            return f"I couldn't find '{query}' on Spotify."

        top_track = tracks[0]
        top_artist = top_track["artists"][0]["name"]

        different_artists = set()
        for t in tracks:
            different_artists.add(t["artists"][0]["name"])

        if len(different_artists) >= 2:
            options = ", ".join(f"{t['name']} by {t['artists'][0]['name']}" for t in tracks[:2])
            return f"I found a few matches: {options}. Which one did you mean?"

        track_uri = top_track["uri"]
        track_name = top_track["name"]

        sp.start_playback(device_id=device_id, uris=[track_uri])
        return f"Playing {track_name} by {top_artist} on Spotify."

    except Exception as e:
        logger.error("Spotify playback error: %s", e)
        return f"I ran into a problem playing that on Spotify: {e}"


def pause_spotify() -> str:
    if sp is None:
        return "Spotify isn't set up correctly right now."
    try:
        sp.pause_playback()
        return "Paused."
    except Exception as e:
        logger.error("Spotify pause error: %s", e)
        return f"I couldn't pause playback: {e}"


def resume_spotify() -> str:
    if sp is None:
        return "Spotify isn't set up correctly right now."
    try:
        sp.start_playback()
        return "Resuming playback."
    except Exception as e:
        logger.error("Spotify resume error: %s", e)
        return f"I couldn't resume playback: {e}"


def skip_spotify() -> str:
    if sp is None:
        return "Spotify isn't set up correctly right now."
    try:
        sp.next_track()
        return "Skipping to the next track."
    except Exception as e:
        logger.error("Spotify skip error: %s", e)
        return f"I couldn't skip the track: {e}"
