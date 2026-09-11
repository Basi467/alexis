# Alexis

A personal, always-listening Windows voice assistant. Wake word -> speech-to-text ->
an LLM agent with ~45 tools -> text-to-speech, plus background tasks (alarm,
reminders, email/calendar monitoring, a crash watchdog) that run unattended via
Windows Task Scheduler.

## Quick start

```bash
pip install -r requirements.txt
```

1. Copy `.env.example` to `.env` and fill in the keys (see below).
2. Download the Vosk wake-word model (`vosk-model-small-en-us-0.15` from
   [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)) and unzip it
   into `models/vosk-model-small-en-us-0.15/`.
3. Install [ffmpeg](https://ffmpeg.org/download.html) and make sure it's on your
   `PATH`. Not strictly required -- TTS playback falls back to a non-streaming,
   non-interruptible mode without it -- but you'll want streaming/barge-in working.
4. `python main.py` -- say "alexis" to wake it up. First run needs internet: the
   speech-to-text and embedding models download automatically from Hugging Face
   the first time they're used, and are cached locally after that.

## Required `.env` values

| Key | Used for |
|---|---|
| `GROQ_API_KEY` | The LLM brain (`openai/gpt-oss-120b`) and vision (`qwen/qwen3.8-27b`) |
| `OPENWEATHER_API_KEY` | Weather in the morning briefing |
| `YOUTUBE_API_KEY` | `play_youtube` |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` / `SPOTIFY_REDIRECT_URI` | Spotify playback control |

Gmail and Google Calendar need a one-time OAuth setup instead of an API key:
create an OAuth app in Google Cloud Console, download the credentials JSON as
`gmail_credentials.json` in the project root, and the first `check_email` /
calendar call will open a browser to complete consent. The resulting token is
cached in `.gmail_token.json`. Both features degrade gracefully (just report
"not set up yet") if this is skipped.

## Architecture, briefly

```
main.py                  wake word -> record -> transcribe -> route -> speak, in a loop
audio/                    wake_word.py (Vosk), recorder.py (VAD-gated recording), beep.py, aec.py (echo cancellation for barge-in)
transcription/            faster-whisper STT
tts/                       edge-tts + ffmpeg decode + sounddevice playback, with barge-in
llm/                       router.py (the agent loop + ~45 tool definitions/handlers), groq_client.py, tools.py
memory/                    SQLite + FAISS: facts, projects, behavior rules, job applications, conversation history
systems/                   one module per capability -- computer_control, gui_control, vision,
                           ui_automation, email_intelligence, calendar_client, web_research, ...
scheduler/                 alarm/reminders/email monitor/calendar monitor/watchdog -- each is a
                           Windows Scheduled Task pointing at a small generated .bat file
tests/                     pytest suite for the highest-risk pure logic (see "Tests" below)
```

**The agent loop** (`llm/router.py`): each user utterance runs through
`chat_completion()` with all tools available; the model can chain up to
`MAX_AGENT_STEPS` (12) tool calls in one turn, reasoning over each result before
deciding the next step or giving a final spoken answer. Some tools
(`CONFIRMATION_REQUIRED_TOOLS`) pause the loop to ask "do you want me to...?"
first; confirming *resumes* the same plan rather than restarting it, and GUI
actions (click/type/submit-key) only need one confirmation per turn, not one
per click.

**Background tasks** all follow the same pattern: a Python module
(`scheduler/whatever.py`) writes a small `.bat` file and registers it as a
Windows Scheduled Task via `schtasks`, with `Hidden`/`WakeToRun` settings applied
afterward. They're launched with `pythonw.exe` (not `python.exe`) so nothing
flashes a console window, and each entry script (`scheduler/deliver_*.py`) bootstraps
`sys.path` itself since Task Scheduler launches it directly by file path.

## Known gotchas (learned the hard way -- read before "fixing" these again)

- **Anything that filters processes by name must check both `python.exe` AND
  `pythonw.exe`.** A launch path's interpreter can be either depending on how it
  was started; `scheduler/system_helpers.py`'s `is_main_already_running()` missing
  this once caused three duplicate `main.py` instances to run simultaneously,
  all fighting over the microphone.
- **Background tasks must use `pythonw.exe`, not `python.exe`,** and the
  scheduled task's `Settings.Hidden` should be `True` -- otherwise every
  background check flashes a visible console window. Also point `schtasks /tr`
  directly at the `.bat` file, not through an `explorer.exe` wrapper.
- **`pythonw.exe` has no console** -- `sys.stdout`/`sys.stderr` are `None`.
  Python's `logging` module silently swallows the resulting write failure
  (doesn't crash), but an *uncaught exception's* default traceback goes nowhere.
  Every entry script's `if __name__ == "__main__":` block wraps `main()` in a
  try/except that logs via the plain-file `log()` before re-raising, specifically
  so a crash stays visible in `scheduler/alarm_log.txt`.
- **`webrtcvad` (plain) fails to import** on this Python/setuptools combination
  (`ModuleNotFoundError: No module named 'pkg_resources'`). Use
  `webrtcvad-wheels` instead -- same `import webrtcvad`, same API, prebuilt wheel.
- **Playwright's own bundled Chromium download fails to launch** on this machine
  specifically (Windows SxS/Fusion can't resolve its private-assembly manifest
  packaging) even after a clean re-download -- not corruption. If browser
  automation is ever needed again, launch with `channel="chrome"` to use the
  system-installed Chrome instead of Playwright's own build.
- **Groq's daily token rate limit is real and has been hit during normal use**
  (200,000 TPD on this account). `RATE_LIMIT_MESSAGE` fails fast rather than
  retrying (retrying within the same day won't help). Cheap classification
  calls (confirmation yes/no, memory update-vs-new, email importance, UI
  element picking) run on `CLASSIFICATION_MODEL` (`openai/gpt-oss-20b`, same
  family, much smaller) specifically to reduce how fast this gets hit --
  keep new classification-style call sites on that model, not the main one.
  Also: the ~51-tool schema catalog itself is ~5500 tokens, sent in full on
  every single step of a multi-step tool-calling chain -- confirmed to be the
  direct cause of hitting the daily limit after any request needing several
  tool calls (a 5-step chain alone could burn 20,000+ tokens on repeated
  schema). Fixed with `_classify_relevant_tools()` in `llm/router.py`: a
  cheap `CLASSIFICATION_MODEL` call picks which `TOOL_CATEGORIES` are
  plausibly relevant and only those tools (plus `ALWAYS_AVAILABLE_TOOL_NAMES`)
  get sent, reused for every step of that turn including a confirmation
  resume. Falls back to the full catalog on any classification failure or
  unparseable reply -- a wrong guess costs tokens, but a silently-unavailable
  tool would break the request outright. Confirmed live: the exact request
  that originally triggered this ("what's on my calendar today and can you
  find my resume on the desktop") dropped from 51 tools to 12. If you add a
  new tool, add its name to `TOOL_CATEGORIES` too, or it'll never be sent to
  the model except via the full-catalog fallback path -- `test_tool_routing.py`
  has a test that catches this.
- **Windows 11's Notepad merges multiple launches into tabs of one window** --
  `win32gui.FindWindow('Notepad', None)` can silently grab a pre-existing tab
  instead of a freshly-launched blank one.
- **`click_on_screen` tries UI Automation first, vision-guessed coordinates
  second.** Vision-only coordinate guessing was tried first and shown (via a
  live Calculator test: 7+3 produced 2, not 10) to be unreliable for precise
  targets; UI Automation reads the real accessibility tree for exact bounding
  boxes and is far more accurate when a window exposes proper control names.
  Vision stays as the fallback for apps that don't (games, canvases, custom UI).
- **`describe_screen`/vision in general hallucinates more on a cluttered,
  multi-window desktop** than on a single focused app -- verified live (invented
  a "zsh" terminal, Blender, Zoom, Discord that weren't real, on a Windows
  machine with none of those open). Trust it less for detailed multi-window
  questions. Also: `ask_vision()` originally set no `max_tokens`, and this model
  reliably free-ran to 1200-1700+ output tokens regardless of the question's
  length or a "be concise" instruction -- on its own enough to exceed Groq's
  1000 output-tokens-per-minute limit and fail the call outright. Now capped at
  `max_tokens=500`, and the prompt explicitly tells it not to invent detail it
  isn't confident about. Confirmed live this materially helps (no more inventing
  entire nonexistent dialog boxes) but doesn't fully fix it -- reading small/dense
  text (a system clock, a packed side panel) is still unreliable; a live test
  read "9/10/2026, 11:44 AM" as "01/10/2024, 12:13 AM". Don't trust vision for
  anything requiring precision on small text -- same principle as the
  UI-Automation-over-vision preference below, just for reading instead of
  clicking.
- **A Google Cloud OAuth app left in "Testing" publishing status auto-expires
  its refresh tokens after ~7 days** -- a Google policy limit, not a config
  mistake. `systems/google_auth.py`'s `get_credentials()` used to fall back to
  an interactive `run_local_server()` browser flow whenever a refresh failed,
  which fires from the *scheduled* email/calendar-check tasks too, not just
  voice commands -- confirmed live: this silently popped open a fresh Google
  sign-in tab from an unattended background task, which then failed with
  "access_denied" since nobody was there to complete it, and would have kept
  recurring every ~30-60 min indefinitely. Fixed: `get_credentials()` now just
  logs and returns `None` on a bad refresh; re-authorizing is a deliberate
  manual action (`python -m systems.google_auth`), never automatic.

## Tests

```bash
python -m pytest tests/
```

56 tests, ~30s (dominated by real model loading transitively pulled in through
`llm.router` -- this is intentional per-request behavior, not something to
mock away). Covers the agent loop's confirmation/resumption logic (the most
complex and most recently bug-fixed part of the app), the tool-relevance
router's fallback safety, the job tracker's company-matching logic, the
interview-prep calendar tie-in, email-extraction parsing, episodic
conversation-history search, and the recorder's VAD gating -- all with mocked
LLM calls / synthetic signals, no real API usage or hardware access. (Note:
`test_router_agent_loop.py`'s mocking of this was incomplete until the
tool-routing fix above -- `ask_groq()`'s two call sites there bypassed the
`chat_completion` mock and made real API calls, adding ~4s of real network
round trips per run; now fully mocked via a `_patch_ask_groq` fixture.) Does
**not** cover anything that needs real audio hardware, a real screen, or real
API responses -- those are verified through live manual testing each time
they change, which these tests don't attempt to replace.

## Currently enabled background tasks

Check what's actually live with `schtasks /query /fo LIST | findstr Alexis`.
As of this writing: `AlexisDailyAlarm`, `Alexis_CalendarMonitor` (hourly),
`Alexis_EmailMonitor` (every 30 min), `Alexis_Watchdog` (every 5 min, relaunches
`main.py` if it's not running). Reminders create their own per-task entries
(`Alexis_Reminder_<id>`) that self-delete after firing (one-time ones) or persist
(daily ones).
