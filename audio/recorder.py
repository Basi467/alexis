import logging

import numpy as np
import sounddevice as sd

try:
    import webrtcvad
except ImportError:
    webrtcvad = None

logger = logging.getLogger(__name__)

# --- Audio configuration ---
SAMPLE_RATE = 16000        # Hz, matches Whisper's expected input
CHUNK_DURATION = 0.2       # seconds per analyzed audio chunk
SILENCE_DURATION = 1.0     # seconds of continuous silence before stopping (lower = snappier, but
                           # more likely to cut off a user who pauses mid-sentence)
MAX_DURATION = 35          # hard safety cap on recording length, seconds -- was 20,
                           # bumped since compound multi-step instructions (e.g.
                           # a long chained GUI task) are common now and a verbose
                           # phrasing could otherwise get cut off mid-sentence
SILENCE_THRESHOLD = 0.02   # fallback RMS threshold, used only if webrtcvad isn't installed

# webrtcvad only accepts 16-bit PCM in exactly 10/20/30ms frames -- 20ms divides
# the 200ms outer chunk evenly (10 sub-frames), unlike 30ms.
_VAD_FRAME_MS = 20
_VAD_FRAME_SAMPLES = int(SAMPLE_RATE * _VAD_FRAME_MS / 1000)
# 0 = least aggressive about filtering non-speech, 3 = most. 2 is a middle ground:
# rejects steady background noise (fans, hum, traffic) that could fool a plain
# energy threshold, without being so strict it clips soft or trailing speech.
_vad = webrtcvad.Vad(2) if webrtcvad is not None else None
if _vad is None:
    logger.warning("webrtcvad not installed -- falling back to plain RMS silence detection.")


def _chunk_has_speech(chunk: np.ndarray, rms_threshold: float) -> bool:
    """True if this ~200ms chunk contains speech. Requires BOTH the calibrated
    RMS threshold and webrtcvad's spectral judgment when webrtcvad is available,
    falling back to the RMS threshold alone otherwise.

    Tried webrtcvad alone first, verified against a real recording of actual
    room background noise (not synthetic) -- it false-positived on 11/15
    quiet-noise chunks, almost certainly from quantization artifacts at very
    low amplitude (RMS ~0.0017, i.e. int16 values mostly in the single/double
    digits) rather than a genuine speech-like signal. The calibrated RMS floor
    already rejects that cleanly since it's tuned to the room's actual noise
    level, so it stays as a hard gate; webrtcvad is layered on top of it to
    additionally reject louder non-speech sounds (a cough, a door click) that
    a bare energy threshold can't distinguish from speech but VAD's spectral
    analysis usually can.
    """
    rms = np.sqrt(np.mean(chunk**2))
    if rms <= rms_threshold:
        return False
    if _vad is None:
        return True

    pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
    usable_len = (len(pcm16) // _VAD_FRAME_SAMPLES) * _VAD_FRAME_SAMPLES
    for start in range(0, usable_len, _VAD_FRAME_SAMPLES):
        frame = pcm16[start:start + _VAD_FRAME_SAMPLES]
        if _vad.is_speech(frame.tobytes(), SAMPLE_RATE):
            return True
    return False


def calibrate_silence_threshold(
    duration: float = 1.0,
    margin: float = 2.0,
    min_threshold: float = 0.005,
    max_threshold: float = 0.15,
) -> float:
    logger.info("Calibrating background noise, please stay quiet...")
    samples = int(duration * SAMPLE_RATE)

    try:
        recording = sd.rec(samples, samplerate=SAMPLE_RATE, channels=1, dtype='float32')
        sd.wait()
    except Exception as e:
        logger.warning("Calibration failed: %s. Using default threshold.", e)
        return SILENCE_THRESHOLD

    noise_rms = np.sqrt(np.mean(recording**2))
    threshold = noise_rms * margin
    threshold = max(min_threshold, min(threshold, max_threshold))

    logger.info("Measured noise floor: %.4f, threshold set to: %.4f", noise_rms, threshold)
    return threshold


def record_until_silence(silence_threshold: float | None = None) -> np.ndarray | None:
    if silence_threshold is None:
        silence_threshold = SILENCE_THRESHOLD

    chunk_samples = int(CHUNK_DURATION * SAMPLE_RATE)
    silence_chunks_needed = int(SILENCE_DURATION / CHUNK_DURATION)
    max_chunks = int(MAX_DURATION / CHUNK_DURATION)

    recorded_frames = []
    silence_counter = 0
    speech_started = False

    logger.info("Listening for your command...")

    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32')
        stream.start()
    except Exception as e:
        logger.error("Microphone error: %s", e)
        return None

    try:
        for _ in range(max_chunks):
            chunk, _ = stream.read(chunk_samples)
            recorded_frames.append(chunk)

            if _chunk_has_speech(chunk.flatten(), silence_threshold):
                speech_started = True
                silence_counter = 0
            elif speech_started:
                silence_counter += 1

            if speech_started and silence_counter >= silence_chunks_needed:
                break
    except Exception as e:
        logger.error("Recording error: %s", e)
        stream.stop()
        stream.close()
        return None

    stream.stop()
    stream.close()

    if not speech_started:
        logger.info("No speech detected.")
        return None

    if not recorded_frames:
        return None

    audio = np.concatenate(recorded_frames)
    return audio.flatten()
