import json
import logging
import queue

import sounddevice as sd
import vosk

from config import VOSK_MODEL_PATH

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

model = vosk.Model(str(VOSK_MODEL_PATH))

audio_queue: queue.Queue = queue.Queue()


def callback(indata, frames, time, status) -> None:
    audio_queue.put(bytes(indata))


def listen_for_wake_word(wake_word: str = "alexis") -> bool:
    recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000, dtype='int16', channels=1, callback=callback):
        logger.info("Listening for wake word...")
        while True:
            data = audio_queue.get()
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
            else:
                result = json.loads(recognizer.PartialResult())

            text = result.get("text", "") or result.get("partial", "")

            if wake_word in text.lower():
                logger.info("Wake word detected")
                return True


if __name__ == "__main__":
    listen_for_wake_word()
