import asyncio
import io
import logging
import queue
import re
import shutil
import subprocess
import threading
import time

import edge_tts
import numpy as np
import sounddevice as sd
from pydub import AudioSegment

from audio.aec import NLMSEchoCanceller

logger = logging.getLogger(__name__)

VOICE = "en-US-AndrewMultilingualNeural"

# ffmpeg is used purely as an MP3 decoder here (pydub already depended on it for the
# same reason), decoding into raw PCM that we play back through sounddevice — the
# same audio backend used everywhere else in this app. An earlier version routed
# playback through `ffplay` directly, which uses SDL for audio output; SDL can pick
# a different default output device than PortAudio/sounddevice does, which produced
# a "no sound" failure mode that was silent (no error) and easy to miss. Decoding
# with ffmpeg and playing with sounddevice keeps one consistent, known-working
# output device.
FFMPEG_PATH = shutil.which("ffmpeg")
if FFMPEG_PATH is None:
    logger.warning("ffmpeg not found on PATH — falling back to buffered (non-streaming, non-interruptible) playback.")

PLAYBACK_SAMPLE_RATE = 16000  # shared by plain playback and the AEC duplex path
BYTES_PER_FRAME = 2           # s16le, mono
PCM_CHUNK_FRAMES = 1600       # 0.1s per read at PLAYBACK_SAMPLE_RATE

# --- Barge-in via acoustic echo cancellation ---
# Alexis's own voice leaks from the speaker into the mic. Rather than guessing a
# loudness threshold on the raw mic signal (which can't tell "my own echo" from
# "someone talking"), an NLMS adaptive filter is fed the exact reference signal
# being played and subtracts its predicted echo out of the mic input in real
# time (see audio/aec.py). Barge-in is then decided from the *residual*, which
# should be quiet during Alexis's own speech and only spike on real, uncorrelated
# sound. This requires a full-duplex stream (one clock for both directions) so
# the reference and mic frames are genuinely time-aligned.
AEC_NUM_TAPS = 2400                    # ~150ms of acoustic path at 16kHz -- covers more of a
                                        # real room's reverb tail than the original 100ms, which
                                        # likely wasn't fully cancelling the echo on real hardware
AEC_STEP_SIZE = 0.2
AEC_ARM_DELAY = 1.2                    # the filter is least converged right when playback starts --
                                        # if it's "catching everything", this is the first suspect
AEC_RESIDUAL_RMS_THRESHOLD = 0.18      # residual RMS, signal normalized to [-1, 1] -- raised from
                                        # 0.08, which still wasn't enough headroom on real hardware
AEC_CONSECUTIVE_BLOCKS_NEEDED = 8      # ~0.8s of sustained residual loudness before it counts

# Off by default: an unreliable barge-in is worse than none, since it cuts off every
# reply. Pass allow_interrupt=True (or set ALLOW_BARGE_IN in main.py) once you've
# confirmed it doesn't false-trigger on your specific mic/speaker setup — tune
# AEC_RESIDUAL_RMS_THRESHOLD and AEC_NUM_TAPS if it does.
DEFAULT_ALLOW_INTERRUPT = False


class _PCMFeeder:
    """Thread-safe buffer: a reader thread pushes decoded PCM bytes into it as
    ffmpeg produces them, and the audio callback pulls fixed-size frames back out.
    `pull` never blocks — if not enough audio is ready yet, it zero-pads, so it's
    safe to call from a real-time audio callback."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._leftover = np.zeros(0, dtype=np.int16)
        self._done = threading.Event()

    def push(self, data: bytes) -> None:
        self._queue.put(np.frombuffer(data, dtype=np.int16))

    def mark_done(self) -> None:
        self._done.set()

    def pull(self, n_frames: int) -> tuple[np.ndarray, bool]:
        """Returns (frames, finished). `frames` is always length n_frames. `finished`
        is True only once ffmpeg has closed its output AND every buffered sample has
        already been returned — i.e. there is truly nothing left to play."""
        available = self._leftover
        while len(available) < n_frames:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break
            available = np.concatenate([available, chunk])

        if len(available) >= n_frames:
            self._leftover = available[n_frames:]
            return available[:n_frames], False

        padded = np.zeros(n_frames, dtype=np.int16)
        padded[:len(available)] = available
        self._leftover = np.zeros(0, dtype=np.int16)
        finished = self._done.is_set() and self._queue.empty()
        return padded, finished


def _read_ffmpeg_stdout(proc: subprocess.Popen, feeder: _PCMFeeder) -> None:
    try:
        while True:
            data = proc.stdout.read(PCM_CHUNK_FRAMES * BYTES_PER_FRAME)
            if not data:
                break
            feeder.push(data)
    except Exception:
        logger.exception("ffmpeg stdout reader failed")
    finally:
        feeder.mark_done()


def _play_plain(proc: subprocess.Popen, interrupted_event: threading.Event, fade_in_seconds: float = 0.0) -> None:
    """Simple output-only playback, used when barge-in isn't requested — no mic
    access, no AEC overhead. fade_in_seconds > 0 ramps volume up from silence
    instead of starting at full volume immediately — for the morning alarm
    greeting specifically, which used to jump straight to full-volume speech
    right as the user is asleep (reported as startling, same complaint that
    led to the wake-up song's own fade-in in systems/wake_up_song.py)."""
    started_at = time.monotonic()
    try:
        with sd.OutputStream(samplerate=PLAYBACK_SAMPLE_RATE, channels=1, dtype='int16') as stream:
            while True:
                if interrupted_event.is_set():
                    break
                data = proc.stdout.read(PCM_CHUNK_FRAMES * BYTES_PER_FRAME)
                if not data:
                    break
                samples = np.frombuffer(data, dtype=np.int16)
                if fade_in_seconds > 0:
                    elapsed = time.monotonic() - started_at
                    volume = min(1.0, max(0.0, elapsed / fade_in_seconds))
                    if volume < 1.0:
                        samples = (samples.astype(np.float32) * volume).astype(np.int16)
                stream.write(samples)
    except Exception:
        logger.exception("Playback thread failed")


def _play_with_aec(proc: subprocess.Popen, interrupted_event: threading.Event) -> None:
    """Full-duplex playback: plays decoded TTS audio and simultaneously reads the
    mic on the same clock, running each block through the NLMS canceller so barge-in
    can be judged from the echo-cancelled residual instead of the raw mic signal."""
    feeder = _PCMFeeder()
    reader_thread = threading.Thread(target=_read_ffmpeg_stdout, args=(proc, feeder), daemon=True)
    reader_thread.start()

    finished_event = threading.Event()
    aec = NLMSEchoCanceller(num_taps=AEC_NUM_TAPS, step_size=AEC_STEP_SIZE)
    consecutive_loud = 0
    started_at = time.monotonic()

    def callback(indata, outdata, frames, time_info, status):
        nonlocal consecutive_loud
        if status:
            logger.debug("Audio stream status: %s", status)

        block, is_finished = feeder.pull(frames)
        outdata[:, 0] = block
        if is_finished:
            finished_event.set()

        if interrupted_event.is_set():
            return

        # Normalized to [-1, 1] before filtering: NLMS's normalization epsilon is sized
        # for unit-scale signals, and TTS audio has frequent silent gaps between words
        # where the raw int16 reference is exactly 0 — feeding raw int16 magnitudes
        # (up to +/-32768) through eps=1e-6 blew the filter up during those gaps.
        near = indata[:, 0].astype(np.float64) / 32768.0
        far = block.astype(np.float64) / 32768.0
        residual = aec.process(near, far)

        if time.monotonic() - started_at < AEC_ARM_DELAY:
            return

        rms = float(np.sqrt(np.mean(residual ** 2)))
        if rms > AEC_RESIDUAL_RMS_THRESHOLD:
            consecutive_loud += 1
            if consecutive_loud >= AEC_CONSECUTIVE_BLOCKS_NEEDED:
                logger.info("Barge-in triggered via AEC residual (rms=%.4f, threshold=%.4f)", rms, AEC_RESIDUAL_RMS_THRESHOLD)
                interrupted_event.set()
        else:
            consecutive_loud = 0

    try:
        with sd.Stream(
            samplerate=PLAYBACK_SAMPLE_RATE, channels=1, dtype='int16',
            blocksize=PCM_CHUNK_FRAMES, callback=callback,
        ):
            while not finished_event.is_set() and not interrupted_event.is_set():
                time.sleep(0.02)
    except Exception:
        logger.exception("AEC playback stream failed")
    finally:
        reader_thread.join(timeout=2)


async def _stream_to_decoder(text: str, stdin, interrupted_event: threading.Event) -> bytes:
    """Streams TTS audio into ffmpeg's stdin as it arrives. Always returns the full
    audio collected so far, so the caller can fall back to buffered playback if the
    pipe dies partway through — the user should still hear the reply once, even if
    streaming playback fails."""
    communicate = edge_tts.Communicate(text, VOICE)
    audio_bytes = b""
    pipe_broken = False
    started_at = time.monotonic()
    logged_first_chunk = False

    async for chunk in communicate.stream():
        if chunk["type"] != "audio":
            continue
        if not logged_first_chunk:
            logger.info("TTS: first audio byte after %.2fs", time.monotonic() - started_at)
            logged_first_chunk = True
        audio_bytes += chunk["data"]

        if interrupted_event.is_set():
            continue  # keep draining the network stream cleanly, stop feeding the decoder

        if not pipe_broken:
            try:
                stdin.write(chunk["data"])
            except BrokenPipeError:
                logger.warning("ffmpeg's pipe closed early; will fall back to buffered playback for this reply.")
                pipe_broken = True

    if not audio_bytes:
        raise RuntimeError("No audio data received")

    return audio_bytes if pipe_broken else b""


def _speak_streaming(text: str, allow_interrupt: bool, fade_in_seconds: float = 0.0) -> bool:
    """Decode TTS audio with ffmpeg and play it through sounddevice as it arrives,
    so playback starts almost immediately instead of waiting for the whole reply
    to be generated. Returns True if the user barged in before playback finished."""
    proc = subprocess.Popen(
        [
            FFMPEG_PATH, "-loglevel", "error", "-f", "mp3", "-i", "pipe:0",
            "-f", "s16le", "-ar", str(PLAYBACK_SAMPLE_RATE), "-ac", "1", "pipe:1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    interrupted_event = threading.Event()
    if allow_interrupt:
        playback_thread = threading.Thread(target=_play_with_aec, args=(proc, interrupted_event))
    else:
        playback_thread = threading.Thread(target=_play_plain, args=(proc, interrupted_event, fade_in_seconds))
    playback_thread.start()

    fallback_audio = b""
    try:
        fallback_audio = asyncio.run(_stream_to_decoder(text, proc.stdin, interrupted_event))
    except Exception:
        logger.exception("Speak failed")
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

        if interrupted_event.is_set():
            # Playback is being cut short deliberately — terminate() will make the
            # reader thread see EOF almost immediately, so a short join is fine here.
            proc.terminate()
            playback_thread.join(timeout=5)
        else:
            # Let it play out in full, however long the reply actually is — a fixed
            # short timeout here previously killed ffmpeg mid-sentence on any reply
            # longer than the timeout, cutting off playback partway through.
            playback_thread.join()

        try:
            proc.wait(timeout=10)
        except Exception:
            logger.warning("ffmpeg didn't exit after playback finished; killing it.")
            proc.kill()

        stderr_output = proc.stderr.read() if proc.stderr else b""
        if stderr_output:
            logger.warning("ffmpeg stderr: %s", stderr_output.decode(errors="replace").strip())

    interrupted = interrupted_event.is_set()
    if fallback_audio and not interrupted:
        logger.info("Replaying via buffered playback after streaming pipe failure.")
        try:
            play_audio_bytes(fallback_audio)
        except Exception:
            logger.exception("Fallback buffered playback also failed")

    return interrupted


async def generate_speech_bytes(text: str, retries: int = 2) -> bytes:
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(text, VOICE)
            audio_bytes = b""

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]

            if not audio_bytes:
                raise RuntimeError("No audio data received")

            return audio_bytes

        except Exception as e:
            logger.warning("TTS attempt %d failed: %s", attempt + 1, e)

    raise RuntimeError("TTS failed after retries")


def play_audio_bytes(audio_bytes: bytes) -> None:
    mp3_buffer = io.BytesIO(audio_bytes)
    segment = AudioSegment.from_file(mp3_buffer, format="mp3")

    samples = np.array(segment.get_array_of_samples())

    if segment.channels == 2:
        samples = samples.reshape((-1, 2))

    samples = samples.astype(np.float32) / (2 ** 15)

    sd.play(samples, samplerate=segment.frame_rate)
    sd.wait()


def _speak_buffered(text: str) -> bool:
    """Fallback used only if ffmpeg isn't available: no streaming, no barge-in."""
    try:
        audio_bytes = asyncio.run(generate_speech_bytes(text))
        play_audio_bytes(audio_bytes)
    except Exception:
        logger.exception("Speak failed")
    return False


async def _warm_up_once() -> None:
    # Runs the stream to completion rather than breaking early on the first audio
    # chunk -- breaking out of the async generator early left its aiohttp session
    # unclosed (confirmed live: "Unclosed client session" warnings on every wake
    # word). "." is a single short clip, so letting it finish costs well under a
    # second and lets edge_tts's own cleanup run normally, same as every other
    # real call site in this file.
    communicate = edge_tts.Communicate(".", VOICE)
    async for _chunk in communicate.stream():
        pass


def warm_up() -> None:
    """Fires a throwaway TTS request in the background to warm up the connection
    to Microsoft's edge-tts backend before the real reply is ready. Confirmed live
    (tts_timing_test, 2026-09-09): a cold connection takes ~8.4s to the first audio
    byte, a connection used moments ago takes ~0.8s -- and since real conversation
    turns are naturally spaced apart, every reply was paying the cold cost. Call
    this the moment the wake word is detected; the several seconds already spent
    recording/transcribing/routing hide this warm-up behind work that's happening
    anyway, so by the time speak() is actually called the connection is primed.
    Never raises -- a failed warm-up just means the real speak() call pays the
    cold-start cost it would have paid anyway, not a crash."""
    def _run() -> None:
        started_at = time.monotonic()
        try:
            asyncio.run(_warm_up_once())
            logger.info("TTS warm-up completed in %.2fs", time.monotonic() - started_at)
        except Exception:
            logger.debug("TTS warm-up failed (non-fatal)", exc_info=True)

    threading.Thread(target=_run, daemon=True, name="tts-warmup").start()


def speak(text: str, allow_interrupt: bool = DEFAULT_ALLOW_INTERRUPT, fade_in_seconds: float = 0.0) -> bool:
    """Speak text aloud. Returns True if the user barged in (started talking) before
    playback finished. fade_in_seconds > 0 ramps volume up from silence instead of
    starting at full volume -- only honored on the plain (allow_interrupt=False)
    playback path; normal conversational replies should stay snappy, this is for
    contexts like the morning alarm greeting where an instant full-volume voice
    would be startling."""
    if not text or not text.strip():
        text = "Okay."

    text = re.sub(r'[*#_`~]', '', text)

    if FFMPEG_PATH is None:
        return _speak_buffered(text)

    return _speak_streaming(text, allow_interrupt, fade_in_seconds)


if __name__ == "__main__":
    speak("Hello, this is a test of streaming text to speech with barge-in support.")
