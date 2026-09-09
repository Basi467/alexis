import logging
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd
import yt_dlp

from tts.edge_speaker import FFMPEG_PATH

logger = logging.getLogger(__name__)

DEFAULT_QUERY = "ytsearch1:AC/DC Back in Black official audio"
MUSIC_SAMPLE_RATE = 44100  # music, not speech -- use full quality, not the 16kHz voice pipeline rate
CHUNK_FRAMES = 4410        # 0.1s per read at MUSIC_SAMPLE_RATE
BYTES_PER_FRAME = 2        # s16le, mono


MAX_DURATION_SECONDS = 30


FADE_IN_SECONDS = 10.0

_stop_event = threading.Event()
_playback_thread: threading.Thread | None = None


def _get_stream_url(query: str) -> str | None:
    ydl_opts = {"format": "bestaudio/best", "quiet": True, "noplaylist": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return info["url"]
    except Exception as e:
        logger.error("Failed to resolve a stream for %r: %s", query, e)
        return None


def _fade_in_volume(elapsed_seconds: float) -> float:

    if elapsed_seconds >= FADE_IN_SECONDS:
        return 1.0
    return max(0.0, elapsed_seconds / FADE_IN_SECONDS)


def _play_loop(stream_url: str, stop_event: threading.Event) -> None:
    started_at = time.monotonic()

    while not stop_event.is_set() and (time.monotonic() - started_at) < MAX_DURATION_SECONDS:
        proc = subprocess.Popen(
            [
                FFMPEG_PATH, "-loglevel", "error", "-i", stream_url,
                "-f", "s16le", "-ar", str(MUSIC_SAMPLE_RATE), "-ac", "1", "pipe:1",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            with sd.OutputStream(samplerate=MUSIC_SAMPLE_RATE, channels=1, dtype='int16') as out_stream:
                while not stop_event.is_set() and (time.monotonic() - started_at) < MAX_DURATION_SECONDS:
                    data = proc.stdout.read(CHUNK_FRAMES * BYTES_PER_FRAME)
                    if not data:
                        break  # song ended naturally -- loop back around and replay
                    volume = _fade_in_volume(time.monotonic() - started_at)
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) * volume
                    out_stream.write(samples.astype(np.int16))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    logger.info("Wake-up song loop finished (stopped=%s)", stop_event.is_set())


def start(query: str = DEFAULT_QUERY) -> bool:

    global _playback_thread

    if FFMPEG_PATH is None:
        logger.warning("ffmpeg not available; skipping wake-up song.")
        return False

    _stop_event.clear()

    stream_url = _get_stream_url(query)
    if stream_url is None:
        return False

    _playback_thread = threading.Thread(target=_play_loop, args=(stream_url, _stop_event), daemon=True)
    _playback_thread.start()
    return True


def stop() -> None:
    _stop_event.set()


def is_playing() -> bool:
    return _playback_thread is not None and _playback_thread.is_alive()
