import logging

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

MODEL_SIZE = "small.en"  # English-only variant -- transcribe() already hardcodes
# language="en" below, so the multilingual "small" model was spending capacity
# on languages this app never uses. Same size/load time, better accuracy and
# speed for English-only use.
INITIAL_PROMPT = "Alexis, JIBA, Muhammed Basith, RAG, FAISS, Groq, FastAPI, LangChain"
# Greedy decoding (beam_size=1) instead of beam search: for short voice commands the
# accuracy gain from beam search is marginal but the latency cost is not.
BEAM_SIZE = 1

try:
    model: WhisperModel | None = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
except Exception:
    logger.exception("Failed to load Whisper model")
    model = None


def transcribe(audio_array: np.ndarray | None) -> str:
    if model is None:
        logger.warning("Whisper model is not loaded.")
        return ""

    if audio_array is None or len(audio_array) == 0:
        return ""

    try:
        segments, info = model.transcribe(
            audio_array,
            language="en",
            vad_filter=True,
            initial_prompt=INITIAL_PROMPT,
            beam_size=BEAM_SIZE
        )

        text = ""
        for segment in segments:
            text += segment.text

        return text.strip()

    except Exception:
        logger.exception("Transcription error")
        return ""
