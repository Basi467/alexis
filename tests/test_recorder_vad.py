"""Covers audio/recorder.py's _chunk_has_speech() -- the RMS-gate + webrtcvad
combination. This exists because a pure-webrtcvad design was tried first and
found (via live testing against a real recording of actual room background
noise) to false-positive 73% of the time on quiet noise, almost certainly from
quantization artifacts at very low amplitude. The fix requires the calibrated
RMS floor to pass BEFORE webrtcvad is even consulted -- these tests lock in
that gating behavior with synthetic signals, not real audio (real speech/noise
accuracy is a live-testing concern already covered manually, not something a
synthetic unit test can meaningfully judge).
"""
import numpy as np

import audio.recorder as recorder
from audio.recorder import _chunk_has_speech, SAMPLE_RATE, CHUNK_DURATION

CHUNK_SAMPLES = int(CHUNK_DURATION * SAMPLE_RATE)


def test_silence_is_never_speech():
    silence = np.zeros(CHUNK_SAMPLES, dtype="float32")
    assert _chunk_has_speech(silence, rms_threshold=0.02) is False


def test_quiet_signal_below_threshold_is_rejected_before_vad_runs():
    """A signal below the RMS floor must be rejected immediately, regardless
    of what webrtcvad would say about it -- this is the actual fix for the
    73%-false-positive-on-quiet-noise bug. A pure tone at very low amplitude
    is used here specifically because it's the kind of signal most likely to
    trip a spectral classifier if the RMS gate weren't short-circuiting first.
    """
    t = np.linspace(0, CHUNK_DURATION, CHUNK_SAMPLES, endpoint=False)
    quiet_tone = (0.001 * np.sin(2 * np.pi * 200 * t)).astype("float32")
    assert _chunk_has_speech(quiet_tone, rms_threshold=0.02) is False


def test_signal_above_threshold_reaches_vad_and_is_not_blocked_by_rms_gate(monkeypatch):
    """Once a chunk clears the RMS floor, the RMS gate itself must not be what
    blocks it -- the final decision is webrtcvad's to make. Stubs webrtcvad's
    is_speech to a controlled True so this is deterministic, decoupled from
    whatever webrtcvad itself happens to think of synthetic noise."""
    monkeypatch.setattr(recorder._vad, "is_speech", lambda frame, rate: True)
    rng = np.random.default_rng(0)
    loud_signal = (rng.standard_normal(CHUNK_SAMPLES) * 0.3).astype("float32")
    assert _chunk_has_speech(loud_signal, rms_threshold=0.02) is True


def test_signal_above_threshold_rejected_if_vad_disagrees(monkeypatch):
    """The inverse: even above the RMS floor, if webrtcvad says no sub-frame
    is speech, the chunk must be rejected -- confirms VAD's judgment is really
    consulted, not bypassed once the RMS gate passes."""
    monkeypatch.setattr(recorder._vad, "is_speech", lambda frame, rate: False)
    rng = np.random.default_rng(0)
    loud_signal = (rng.standard_normal(CHUNK_SAMPLES) * 0.3).astype("float32")
    assert _chunk_has_speech(loud_signal, rms_threshold=0.02) is False


def test_threshold_boundary_is_exclusive():
    """A chunk at exactly the threshold (not above it) should be treated as
    silence -- matches the `rms <= rms_threshold: return False` gate."""
    constant = np.full(CHUNK_SAMPLES, 0.02, dtype="float32")
    rms = np.sqrt(np.mean(constant**2))
    assert _chunk_has_speech(constant, rms_threshold=rms) is False
