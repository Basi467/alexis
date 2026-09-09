import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# A soft two-note ascending chime (like Siri/Google Assistant's listening cue)
# instead of a single flat tone, which reads as an electronic "beep" rather than
# a natural, pleasant sound. D5 -> G5 is a clean perfect-fourth interval.
NOTE_FREQUENCIES = (587.33, 783.99)
NOTE_DURATION = 0.09
GAP_DURATION = 0.03
VOLUME = 0.5
DECAY_RATE = 8.0     # higher = faster, more bell-like decay
ATTACK_SECONDS = 0.003  # just enough to avoid a click at the very start of each note


def _note(frequency: float, duration: float) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # A touch of the second harmonic gives it a rounder, less synthetic timbre
    # than a bare sine wave would have.
    wave = np.sin(2 * np.pi * frequency * t) + 0.25 * np.sin(2 * np.pi * frequency * 2 * t)

    envelope = np.exp(-DECAY_RATE * t)  # natural bell-like decay, not a flat tone that just stops
    attack_samples = max(1, int(ATTACK_SECONDS * SAMPLE_RATE))
    envelope[:attack_samples] *= np.linspace(0, 1, attack_samples)

    return wave * envelope


def _generate_chime() -> np.ndarray:
    gap = np.zeros(int(SAMPLE_RATE * GAP_DURATION))
    notes = [_note(f, NOTE_DURATION) for f in NOTE_FREQUENCIES]
    combined = np.concatenate([notes[0], gap, notes[1]])
    combined = combined / np.max(np.abs(combined)) * VOLUME
    return (combined * 32767).astype(np.int16)


def play_listening_beep() -> None:
    try:
        samples = _generate_chime()
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
            stream.write(samples)
    except Exception as e:
        logger.warning("Failed to play listening beep: %s", e)
