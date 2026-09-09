import logging
import sys

import win32api
import win32event
import winerror

from config import ALARM_LOG_FILE, configure_logging

# Logging must be set up before anything else is imported: main.py normally runs
# under pythonw.exe (no console), where sys.stdout/sys.stderr are None -- an
# import failure here (a missing model file, a broken dependency) would
# otherwise crash with its traceback going nowhere, exactly the kind of silent
# failure this file-based logging exists to prevent.
configure_logging(log_file=ALARM_LOG_FILE)
logger = logging.getLogger(__name__)

# Hard single-instance guard at the OS level. The watchdog's "is main.py already
# running" check (scheduler/system_helpers.py) is a check-then-launch with a race
# window, and it does nothing at all to stop a *manual* second launch (e.g.
# running `python main.py` in a terminal to test something while the background
# pythonw.exe instance from the watchdog/Task Scheduler is already up). Two live
# instances each open the mic independently, so one "alexis" gets picked up by
# both and they answer on top of each other -- reported live as "multiple alexis
# running". A named mutex makes a second instance impossible regardless of how
# it was started, instead of just discouraging it. Keep a reference to the
# handle for the life of the process -- letting it get garbage-collected would
# release the mutex early.
_instance_mutex = win32event.CreateMutex(None, False, "Global\\AlexisSingleInstance")
if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
    logger.warning("Another Alexis instance is already running -- exiting so we don't double up on the mic.")
    sys.exit(0)

try:
    from audio.beep import play_listening_beep
    from audio.wake_word import listen_for_wake_word
    from audio.recorder import record_until_silence, calibrate_silence_threshold
    from transcription.whisper_stt import transcribe
    from tts.edge_speaker import speak, warm_up as warm_up_tts
    from llm.router import route
    from memory.episodic import log_exchange
    import systems.wake_up_song as wake_up_song
    import ui.overlay as overlay
except Exception:
    logger.exception("Alexis failed to start -- a required module or model failed to load.")
    raise

MAX_CONSECUTIVE_SILENCES = 2
ALLOW_BARGE_IN = True


def handle_conversation() -> None:
    in_conversation = True
    history = []
    pending_confirmation = None
    consecutive_silences = 0
    # Calibrated once per conversation, not per turn — the noise floor doesn't
    # change turn to turn, and recalibrating cost ~1s of dead air every time.
    threshold = calibrate_silence_threshold()
    while in_conversation:
        overlay.set_state("listening")
        play_listening_beep()
        audio_data = record_until_silence(silence_threshold=threshold)

        if audio_data is None:
            consecutive_silences += 1
            if consecutive_silences >= MAX_CONSECUTIVE_SILENCES:
                overlay.set_state("speaking")
                speak("I'll stop listening for now. Just say my name when you need me.", allow_interrupt=ALLOW_BARGE_IN)
                in_conversation = False
            continue

        consecutive_silences = 0

        overlay.set_state("thinking")
        user_text = transcribe(audio_data)

        if not user_text.strip():
            continue

        overlay.add_transcript("You", user_text)

        result = route(user_text, history, pending_confirmation)
        pending_confirmation = result.get("pending_confirmation")

        overlay.add_transcript("Alexis", result["text"])
        overlay.set_state("speaking")
        interrupted = speak(result["text"], allow_interrupt=ALLOW_BARGE_IN)
        if interrupted:
            logger.info("User barged in — cutting reply short and listening immediately.")

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": result["text"]})

        try:
            log_exchange(user_text, result["text"])
        except Exception:
            logger.exception("Failed to log exchange to conversation history -- continuing.")

        if result["action"] == "exit":
            in_conversation = False


if __name__ == "__main__":
    # Launched with this flag by scheduler/deliver_alarm.py right after the morning
    # greeting. The song keeps looping in the background (mic input and speaker
    # output are separate streams, so wake-word listening isn't blocked by it) until
    # you actually engage Alexis — saying the wake word is treated as "I'm awake."
    play_wake_song = "--play-wake-song" in sys.argv
    if play_wake_song:
        try:
            logger.info("Starting wake-up song.")
            wake_up_song.start()
        except Exception:
            # This runs right after the morning alarm greeting -- a failure here
            # (network issue, yt-dlp error) must not take down the whole process
            # and leave Alexis never actually listening after the alarm fires.
            logger.exception("Failed to start wake-up song -- continuing without it.")
            play_wake_song = False

    overlay.start()

    while True:
        try:
            overlay.set_state("sleeping")
            listen_for_wake_word()
            overlay.set_state("awake")
            warm_up_tts()
            if play_wake_song:
                logger.info("Wake word detected — stopping wake-up song.")
                wake_up_song.stop()
                play_wake_song = False
            handle_conversation()
        except Exception:
            logger.exception("Unhandled error in main loop, restarting listening loop.")