import numpy as np


class NLMSEchoCanceller:
    """Adaptive filter (Normalized Least Mean Squares) that learns the acoustic
    path from speaker to mic and subtracts the predicted echo from the mic
    signal — the standard technique behind real acoustic echo cancellation
    (WebRTC's AEC is a highly-optimized version of the same family of filter).

    Only the part of the mic signal that's *correlated* with what was just
    played gets removed. Genuine speech, being uncorrelated with the reference
    signal, mostly survives in the residual — which is what makes this usable
    for barge-in detection: check the residual's loudness, not the raw mic's.

    Requires `near` (mic) and `far` (reference/speaker) to be time-aligned,
    same sample rate, same clock — i.e. frames pulled from a single full-duplex
    audio stream, not two independently-clocked streams.
    """

    def __init__(self, num_taps: int = 1600, step_size: float = 0.1, eps: float = 1e-2):
        # eps sized for signals normalized to roughly [-1, 1] (e.g. int16 audio / 32768).
        # Speech/reference audio has real silent gaps where the reference buffer goes to
        # exactly 0 — too small an eps there makes mu / (buf@buf + eps) spike and blows
        # the filter up on the very next update, even for a tiny error.
        self.num_taps = num_taps
        self.mu = step_size
        self.eps = eps
        self.weights = np.zeros(num_taps, dtype=np.float64)
        self.history = np.zeros(num_taps, dtype=np.float64)

    def process(self, near: np.ndarray, far: np.ndarray) -> np.ndarray:
        """near/far: equal-length 1-D float arrays for the same time window.
        Returns the residual (echo-cancelled) signal, same length as the input."""
        n = len(near)
        residual = np.empty(n, dtype=np.float64)
        w = self.weights
        buf = self.history
        mu = self.mu
        eps = self.eps

        for i in range(n):
            buf[1:] = buf[:-1]
            buf[0] = far[i]
            estimate = w @ buf
            error = near[i] - estimate
            residual[i] = error
            norm = buf @ buf + eps
            w += (mu * error / norm) * buf

        return residual
