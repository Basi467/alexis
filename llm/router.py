import json
import logging
import time
import webbrowser
from datetime import datetime
from typing import Any, Callable

from llm.groq_client import ask_groq, chat_completion, CLASSIFICATION_MODEL
from llm.tools import (
    ALL_TOOLS, DOCUMENTS_TOOL, OPEN_FILE_TOOL, OPEN_APP_TOOL,
    WEATHER_TOOL, DATETIME_TOOL, END_CONVERSATION_TOOL
)
from memory.store import (
    MEMORY_TOOL, RECALL_MEMORY_TOOL, UPDATE_PROJECT_TOOL, RECALL_PROJECT_TOOL, SAVE_RULE_TOOL,
    remember, recall, update_project, recall_project, save_rule, get_all_rules,
)
from systems.apps import open_app
from systems.computer_control import (
    set_volume, mute_volume, unmute_volume, set_brightness,
    close_app, switch_to_app, lock_computer, restart_computer, shutdown_computer, cancel_shutdown,
)
from systems.datetimeandweather_info import get_datetime_info, get_weather
from systems.file_search import open_file, find_file
from systems.doc_store import search_documents, set_last_found_file, get_last_found_file
from systems.youtube_search import search_youtube
from systems.spotify_control import play_on_spotify, skip_spotify, pause_spotify, resume_spotify
from systems.web_functions import open_website, search_web, open_gmail
from systems.web_research import search_and_read
from systems.vision import describe_screen, locate_element_on_screen
from systems.gui_control import click_at, type_text as type_text_gui, press_key as press_key_gui, is_submit_like_key, scroll as scroll_gui
from systems.ui_automation import find_control_center
from scheduler.alarm import set_daily_alarm
from scheduler.reminders import set_reminder, list_reminders, cancel_reminder
from scheduler.email_monitor import enable_email_monitoring, disable_email_monitoring
from systems.email_intelligence import check_for_important_emails, describe_important_emails
from memory.job_tracker import list_applications, get_application, upsert_application
from memory.episodic import (
    search_conversation_history, describe_conversation_history, SEARCH_CONVERSATION_HISTORY_TOOL,
)
from systems.gmail_client import is_configured as is_gmail_configured
from systems.calendar_client import (
    list_events as list_calendar_events_raw, create_event as create_calendar_event_raw,
    find_event_by_summary, delete_event as delete_calendar_event,
    is_configured as is_calendar_configured,
)
from scheduler.calendar_monitor import enable_calendar_monitoring, disable_calendar_monitoring

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT_TEXT = (
    "You are Alexis, a voice assistant. Your replies are spoken aloud, not read as text. "
    "Keep replies short and conversational. Never use markdown, asterisks, hashtags, bullet "
    "points, or any text formatting symbols, and if it's an example say 'example' not 'e.g.'\n\n"
    "Before saying you don't know something about the user — their preferences, name, "
    "background, or anything else about them — call recall_memory first to actually check. "
    "This also applies before doing something that could be personalized to a known "
    "preference (like playing music), not just when directly asked about it. Don't assume "
    "you don't know something just because it isn't in the current conversation."
)


def _build_system_prompt() -> dict:
    """Rebuilt on every turn (a cheap SQLite SELECT) so a behavior rule saved mid-
    conversation applies starting on the very next reply, not just future sessions."""
    rules = get_all_rules()
    # Needed so set_reminder can compute an absolute run_time from relative phrasing
    # like "in 20 minutes" or "tomorrow at 3pm" -- without this the model has no way
    # to know what "now" actually is.
    content = BASE_SYSTEM_PROMPT_TEXT + f"\n\nCurrent date and time: {datetime.now().strftime('%A, %B %d, %Y, %H:%M')}."
    if rules:
        content += "\n\nAdditionally, the user has asked you to follow these standing behavioral rules:\n"
        content += "\n".join(f"- {rule}" for rule in rules)
    return {"role": "system", "content": content}


TOOLS = ALL_TOOLS + [
    MEMORY_TOOL, RECALL_MEMORY_TOOL, UPDATE_PROJECT_TOOL, RECALL_PROJECT_TOOL, SAVE_RULE_TOOL,
    SEARCH_CONVERSATION_HISTORY_TOOL,
]
VOICE_CONSTRAINT = (
    "Keep your answer short and conversational — 2-4 sentences, since this will be spoken aloud, "
    "not read as text. Do not use markdown, tables, bullet points, headers, or special formatting."
)

# Tools consequential enough to confirm before executing — deliberately a short list.
# Most tools here are read-only, trivially reversible (pause/resume, open an app you can
# just close), or purely local (saving a fact), so asking "are you sure?" before every one
# of them would just be friction with no real safety benefit. These are the exceptions:
# set_daily_alarm changes a system-level scheduled task and power setting; open_website
# opens an arbitrary URL the LLM chose — including one it might have picked up from
# untrusted document content (see the doc RAG prompt-injection note from the code review);
# close_app can lose unsaved work in whatever it closes; restart/shutdown affect the whole
# system, not just Alexis, and are the least reversible actions in the entire tool list.
CONFIRMATION_REQUIRED_TOOLS = {
    "set_daily_alarm", "open_website", "restart_computer", "shutdown_computer", "set_reminder",
    "enable_email_monitoring", "create_calendar_event", "cancel_calendar_event",
    "enable_calendar_monitoring", "click_on_screen", "type_text",
}

# close_app is a special case: confirmation only matters for the kind of app that can
# hold unsaved work (editors, IDEs, office apps). Closing Chrome or a music player
# almost never loses anything, so asking "are you sure?" every time would just be
# friction — the risk is specifically about losing unsaved edits, not about apps
# in general. Matched by substring, since app names are short single words/phrases,
# not full sentences (unlike the exit-phrase check, which needs an exact match to
# avoid false-triggering on a sentence that merely contains the word "stop").
EDITOR_LIKE_APPS = {
    "notepad", "word", "excel", "powerpoint", "onenote", "code", "vscode",
    "visual studio", "sublime", "vim", "emacs", "notion", "photoshop",
    "illustrator", "premiere",
}


def _requires_confirmation(tool_call: dict[str, Any]) -> bool:
    name = tool_call["name"]
    if name == "close_app":
        app_name = tool_call["arguments"]["app_name"].lower()
        return any(keyword in app_name for keyword in EDITOR_LIKE_APPS)
    # press_key is low-risk for navigation keys (arrows, tab, escape...) but
    # Enter/Return commonly submits a form or sends a message -- exactly the
    # kind of consequential, hard-to-undo action the confirmation system exists
    # for, so only that subset gets gated, not every key press.
    if name == "press_key":
        return is_submit_like_key(tool_call["arguments"]["key"])
    return name in CONFIRMATION_REQUIRED_TOOLS


# A single GUI task is often many clicks/types/submits in a row (e.g. entering a
# calculation button by button) -- re-asking "do you want me to click X?" before
# every single one of them is pure friction once the user has already approved
# the task. Once one of these has been confirmed, later ones in the SAME turn
# skip asking again; a different, unrelated confirmation-required tool appearing
# mid-chain (e.g. shutdown_computer) still asks normally regardless.
GUI_ACTION_TOOLS = {"click_on_screen", "type_text"}


def _is_gui_action(tool_call: dict[str, Any]) -> bool:
    name = tool_call["name"]
    if name in GUI_ACTION_TOOLS:
        return True
    if name == "press_key":
        return is_submit_like_key(tool_call["arguments"]["key"])
    return False


def _describe_pending_action(tool_call: dict[str, Any]) -> str:
    name = tool_call["name"]
    args = tool_call["arguments"]
    if name == "set_daily_alarm":
        return f"Do you want me to set your daily alarm for {args['time']}?"
    if name == "set_reminder":
        when = args["run_time"]
        cadence = "every day" if args.get("recurrence") == "daily" else ""
        return f"Do you want me to set a reminder to {args['message']} {cadence} at {when}?".replace("  ", " ")
    if name == "open_website":
        return f"Do you want me to open {args['site']}?"
    if name == "close_app":
        return f"Do you want me to close {args['app_name']}? Any unsaved work in it could be lost."
    if name == "restart_computer":
        return "Do you want me to restart the computer?"
    if name == "shutdown_computer":
        return "Do you want me to shut down the computer?"
    if name == "enable_email_monitoring":
        return "Do you want me to start watching your email in the background and tell you about important ones?"
    if name == "create_calendar_event":
        return f"Do you want me to add '{args['summary']}' to your calendar from {args['start_time']} to {args['end_time']}?"
    if name == "cancel_calendar_event":
        return f"Do you want me to remove '{args['identifier']}' from your calendar?"
    if name == "enable_calendar_monitoring":
        return "Do you want me to start watching your calendar in the background and give you a heads-up before events?"
    if name == "click_on_screen":
        return f"Do you want me to click on {args['description']}?"
    if name == "type_text":
        return f'Do you want me to type "{args["text"]}"?'
    if name == "press_key":
        return f"Do you want me to press {args['key']}?"
    return "Do you want me to go ahead with that?"


def _classify_confirmation(question: str, reply: str) -> str:
    """Returns 'yes', 'no', or 'unclear' (the reply doesn't answer the question at
    all — e.g. the user changed the subject instead of confirming or declining)."""
    prompt = (
        f'You asked the user: "{question}"\n'
        f'They replied: "{reply}"\n\n'
        "Does their reply mean YES (confirm, go ahead), NO (cancel, don't do it), or is it "
        "UNRELATED to answering that question (they changed the subject or asked something else)?\n"
        "Respond with exactly one word: YES, NO, or UNRELATED."
    )
    result, _ = ask_groq(prompt, model=CLASSIFICATION_MODEL)
    result = result.strip().upper()
    if "YES" in result:
        return "yes"
    if "NO" in result:
        return "no"
    return "unclear"

# Each handler receives the tool call's arguments and returns (text, is_direct_reply).
# is_direct_reply=True means the text is spoken as-is; False means it's fed back to the
# LLM as context so it can phrase a natural reply around it.
ToolHandler = Callable[[dict[str, Any]], tuple[str, bool]]


def _save_memory(args: dict[str, Any]) -> tuple[str, bool]:
    remember(args["fact"])
    return (
        f"You just saved this fact about the user. Continue the conversation naturally, "
        f"responding to what they actually said. {VOICE_CONSTRAINT}",
        False,
    )


def _save_rule(args: dict[str, Any]) -> tuple[str, bool]:
    save_rule(args["rule"])
    return (
        f"You just saved this standing behavioral rule, which will apply starting now. "
        f"Acknowledge it naturally. {VOICE_CONSTRAINT}",
        False,
    )


def _recall_memory(args: dict[str, Any]) -> tuple[str, bool]:
    found = recall(args["query"], max_results=2)
    if found:
        return f"Relevant things you know about the user: {' | '.join(found)}. {VOICE_CONSTRAINT}", False
    return f"You don't have that information stored yet. Let the user know honestly. {VOICE_CONSTRAINT}", False


def _search_conversation_history(args: dict[str, Any]) -> tuple[str, bool]:
    results = search_conversation_history(
        query=args.get("query"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    if not results:
        return "Nothing found in past conversation history matching that. Let the user know honestly.", False
    summary = describe_conversation_history(results)
    return f"Past conversation history found: {summary} {VOICE_CONSTRAINT}", False


def _update_project(args: dict[str, Any]) -> tuple[str, bool]:
    update_project(args["name"], args["status"])
    return (
        f"You just saved this project update. Continue the conversation naturally, "
        f"responding to what they actually said. {VOICE_CONSTRAINT}",
        False,
    )


def _recall_project(args: dict[str, Any]) -> tuple[str, bool]:
    project = recall_project(args["name"])
    if project:
        return (
            f"Current status of project '{project['name']}': {project['status']}. {VOICE_CONSTRAINT}",
            False,
        )
    return f"You don't have that project tracked yet. Let the user know honestly. {VOICE_CONSTRAINT}", False


def _search_documents(args: dict[str, Any]) -> tuple[str, bool]:
    results = search_documents(args["query"])
    if not results:
        return f"No relevant documents were found. Let the user know honestly. {VOICE_CONSTRAINT}", False
    set_last_found_file(results[0]["source_path"])
    context = "\n\n".join(f"From {r['source_file']}: {r['text']}" for r in results)
    return (
        f"Answer using this information from the user's documents:\n\n{context}\n\n"
        f"Briefly mention which file the information came from. {VOICE_CONSTRAINT}"
    ), False


def _open_last_file(args: dict[str, Any]) -> tuple[str, bool]:
    last_file = get_last_found_file()
    if last_file:
        return open_file(last_file), True
    return "There's no recently found file to open. Let the user know.", False


def _find_file_by_name(args: dict[str, Any]) -> tuple[str, bool]:
    matches = find_file(args["query"])
    if matches:
        set_last_found_file(matches[0]["path"])
        return f"I found a file named {matches[0]['name']}. Want me to open it?", True
    return f"I couldn't find a file matching '{args['query']}'.", True


def _open_app(args: dict[str, Any]) -> tuple[str, bool]:
    return open_app(args["app_name"]), True


def _get_weather(args: dict[str, Any]) -> tuple[str, bool]:
    return get_weather(), True


def _get_datetime(args: dict[str, Any]) -> tuple[str, bool]:
    return get_datetime_info(), True


def _end_conversation(args: dict[str, Any]) -> tuple[str, bool]:
    return "Okay, let me know if you need me.", True


def _play_youtube(args: dict[str, Any]) -> tuple[str, bool]:
    video_url, title = search_youtube(args["query"])
    if video_url:
        webbrowser.open(video_url)
        return f"Playing {title} on YouTube.", True
    return f"I couldn't find that on YouTube. {title}", True


def _play_spotify(args: dict[str, Any]) -> tuple[str, bool]:
    return play_on_spotify(args["query"]), True


def _pause_spotify(args: dict[str, Any]) -> tuple[str, bool]:
    return pause_spotify(), True


def _resume_spotify(args: dict[str, Any]) -> tuple[str, bool]:
    return resume_spotify(), True


def _skip_spotify(args: dict[str, Any]) -> tuple[str, bool]:
    return skip_spotify(), True


def _open_website(args: dict[str, Any]) -> tuple[str, bool]:
    return open_website(args["site"]), True


def _open_gmail(args: dict[str, Any]) -> tuple[str, bool]:
    return open_gmail(), True


def _search_web(args: dict[str, Any]) -> tuple[str, bool]:
    return search_web(args["query"]), True


def _search_and_answer(args: dict[str, Any]) -> tuple[str, bool]:
    result = search_and_read(args["query"])
    if result is None:
        return "No usable web results were found. Let the user know honestly.", False
    return (
        f"Answer the user's question using this information from {result['title']} "
        f"({result['url']}):\n\n{result['text']}\n\n"
        f"Briefly mention which source it came from. {VOICE_CONSTRAINT}"
    ), False


def _list_job_applications(args: dict[str, Any]) -> tuple[str, bool]:
    company = args.get("company")
    if company:
        app = get_application(company)
        if not app:
            return f"No tracked application found for '{company}'. Let the user know honestly.", False
        role_part = f" ({app['role']})" if app["role"] else ""
        return (
            f"Application status for {app['company']}{role_part}: {app['status']}, "
            f"last updated {app['updated_at']}. {VOICE_CONSTRAINT}"
        ), False

    apps = list_applications(args.get("status"))
    if not apps:
        return "No tracked job applications found. Let the user know honestly.", False
    summary = "; ".join(
        f"{a['company']}{' (' + a['role'] + ')' if a['role'] else ''}: {a['status']}" for a in apps
    )
    return f"Tracked job applications: {summary}. {VOICE_CONSTRAINT}", False


def _update_job_application(args: dict[str, Any]) -> tuple[str, bool]:
    upsert_application(args["company"], args.get("role"), args["status"])
    return (
        f"You just saved this job application update. Continue the conversation "
        f"naturally, responding to what they actually said. {VOICE_CONSTRAINT}",
        False,
    )


def _look_at_screen(args: dict[str, Any]) -> tuple[str, bool]:
    question = args["question"]
    description = describe_screen(question)
    if description is None:
        return "Screen reading isn't available right now. Let the user know honestly.", False
    return (
        f"Here's what's visible on the user's screen right now: {description}\n\n"
        f"Answer the user using this. {VOICE_CONSTRAINT}"
    ), False


def _click_on_screen(args: dict[str, Any]) -> tuple[str, bool]:
    description = args["description"]
    # UI Automation (the app's own accessibility tree) gives an exact bounding
    # box when available, and is tried first for that reason -- vision-guessed
    # pixel coordinates are a fallback for apps with no accessible control
    # names (games, canvases, custom-rendered UI), not the primary path.
    location = find_control_center(description) or locate_element_on_screen(description)
    if location is None:
        return f"Couldn't find '{description}' on the screen. Let the user know honestly.", False
    click_at(*location)
    return (
        f"Clicked on {description}. If completing the user's request needs more "
        f"actions (more clicks, typing, key presses), do the next one now instead "
        f"of stopping here. Otherwise, tell them naturally what you did. {VOICE_CONSTRAINT}"
    ), False


def _type_text(args: dict[str, Any]) -> tuple[str, bool]:
    text = args["text"]
    type_text_gui(text)
    return (
        f'Typed "{text}". If completing the user\'s request needs more actions, '
        f"do the next one now instead of stopping here. Otherwise, tell them "
        f"naturally what you did. {VOICE_CONSTRAINT}"
    ), False


def _press_key(args: dict[str, Any]) -> tuple[str, bool]:
    key = args["key"]
    if not press_key_gui(key):
        return f"'{key}' isn't a key I recognize. Let the user know honestly.", False
    return (
        f"Pressed {key}. If completing the user's request needs more actions, do "
        f"the next one now instead of stopping here. Otherwise, tell them "
        f"naturally what you did. {VOICE_CONSTRAINT}"
    ), False


def _scroll_screen(args: dict[str, Any]) -> tuple[str, bool]:
    scroll_gui(args["amount"])
    return (
        f"Scrolled. If completing the user's request needs more actions, do the "
        f"next one now instead of stopping here. Otherwise, tell them naturally "
        f"what you did. {VOICE_CONSTRAINT}"
    ), False


def _set_daily_alarm(args: dict[str, Any]) -> tuple[str, bool]:
    _success, message = set_daily_alarm(args["time"])
    return message, True


def _set_volume(args: dict[str, Any]) -> tuple[str, bool]:
    return set_volume(args["percent"]), True


def _mute_volume(args: dict[str, Any]) -> tuple[str, bool]:
    return mute_volume(), True


def _unmute_volume(args: dict[str, Any]) -> tuple[str, bool]:
    return unmute_volume(), True


def _set_brightness(args: dict[str, Any]) -> tuple[str, bool]:
    return set_brightness(args["percent"]), True


def _close_app(args: dict[str, Any]) -> tuple[str, bool]:
    return close_app(args["app_name"]), True


def _switch_to_app(args: dict[str, Any]) -> tuple[str, bool]:
    return switch_to_app(args["app_name"]), True


def _lock_computer(args: dict[str, Any]) -> tuple[str, bool]:
    return lock_computer(), True


def _restart_computer(args: dict[str, Any]) -> tuple[str, bool]:
    return restart_computer(), True


def _shutdown_computer(args: dict[str, Any]) -> tuple[str, bool]:
    return shutdown_computer(), True


def _cancel_shutdown(args: dict[str, Any]) -> tuple[str, bool]:
    return cancel_shutdown(), True


def _set_reminder(args: dict[str, Any]) -> tuple[str, bool]:
    _success, message = set_reminder(args["message"], args["run_time"], args.get("recurrence", "once"))
    return message, True


def _list_reminders(args: dict[str, Any]) -> tuple[str, bool]:
    reminders = list_reminders()
    if not reminders:
        return "You don't have any reminders set. Let the user know honestly.", False
    summary = "; ".join(f"{r['message']} at {r['run_time']} ({r['recurrence']})" for r in reminders)
    return f"The user's current reminders: {summary}. {VOICE_CONSTRAINT}", False


def _cancel_reminder(args: dict[str, Any]) -> tuple[str, bool]:
    _success, message = cancel_reminder(args["identifier"])
    return message, True


def _check_email(args: dict[str, Any]) -> tuple[str, bool]:
    if not is_gmail_configured():
        return "Gmail isn't set up yet. Let the user know they need to complete the one-time setup first.", False

    important = check_for_important_emails()
    if not important:
        return "No important emails right now. Let the user know honestly.", False

    summary = describe_important_emails(important)
    return (
        f"Important emails found: {summary}. If the user wants to see them, offer to "
        f"open Gmail using the open_gmail tool -- not open_app, they have no Gmail "
        f"desktop app installed. {VOICE_CONSTRAINT}"
    ), False


def _enable_email_monitoring(args: dict[str, Any]) -> tuple[str, bool]:
    if not is_gmail_configured():
        return "Gmail isn't set up yet, so I can't monitor it. Let the user know they need to complete the one-time setup first.", False
    _success, message = enable_email_monitoring()
    return message, True


def _disable_email_monitoring(args: dict[str, Any]) -> tuple[str, bool]:
    _success, message = disable_email_monitoring()
    return message, True


def _get_calendar_events(args: dict[str, Any]) -> tuple[str, bool]:
    if not is_calendar_configured():
        return "Calendar isn't set up yet. Let the user know they need to complete the one-time setup first.", False

    events = list_calendar_events_raw(args["start_date"], days=args.get("days", 1))
    if not events:
        return "No calendar events found for that period. Let the user know honestly.", False

    summary = "; ".join(f"{e['summary']} at {e['start']}" for e in events)
    return f"The user's calendar events: {summary}. {VOICE_CONSTRAINT}", False


def _create_calendar_event(args: dict[str, Any]) -> tuple[str, bool]:
    _success, message = create_calendar_event_raw(args["summary"], args["start_time"], args["end_time"])
    return message, True


def _cancel_calendar_event(args: dict[str, Any]) -> tuple[str, bool]:
    event = find_event_by_summary(args["identifier"])
    if event is None:
        return f"I couldn't find a calendar event matching '{args['identifier']}'.", True
    _success, message = delete_calendar_event(event["id"])
    return message, True


def _enable_calendar_monitoring(args: dict[str, Any]) -> tuple[str, bool]:
    if not is_calendar_configured():
        return "Calendar isn't set up yet, so I can't monitor it. Let the user know they need to complete the one-time setup first.", False
    _success, message = enable_calendar_monitoring()
    return message, True


def _disable_calendar_monitoring(args: dict[str, Any]) -> tuple[str, bool]:
    _success, message = disable_calendar_monitoring()
    return message, True


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "save_memory": _save_memory,
    "recall_memory": _recall_memory,
    "search_conversation_history": _search_conversation_history,
    "save_behavior_rule": _save_rule,
    "update_project": _update_project,
    "recall_project": _recall_project,
    "search_documents": _search_documents,
    "open_last_file": _open_last_file,
    "find_file_by_name": _find_file_by_name,
    "open_app": _open_app,
    "get_weather": _get_weather,
    "get_datetime": _get_datetime,
    "end_conversation": _end_conversation,
    "play_youtube": _play_youtube,
    "play_spotify": _play_spotify,
    "pause_spotify": _pause_spotify,
    "resume_spotify": _resume_spotify,
    "skip_spotify": _skip_spotify,
    "open_website": _open_website,
    "open_gmail": _open_gmail,
    "search_web": _search_web,
    "search_and_answer": _search_and_answer,
    "list_job_applications": _list_job_applications,
    "update_job_application": _update_job_application,
    "look_at_screen": _look_at_screen,
    "click_on_screen": _click_on_screen,
    "type_text": _type_text,
    "press_key": _press_key,
    "scroll_screen": _scroll_screen,
    "set_daily_alarm": _set_daily_alarm,
    "set_volume": _set_volume,
    "mute_volume": _mute_volume,
    "unmute_volume": _unmute_volume,
    "set_brightness": _set_brightness,
    "close_app": _close_app,
    "switch_to_app": _switch_to_app,
    "lock_computer": _lock_computer,
    "restart_computer": _restart_computer,
    "shutdown_computer": _shutdown_computer,
    "cancel_shutdown": _cancel_shutdown,
    "set_reminder": _set_reminder,
    "list_reminders": _list_reminders,
    "cancel_reminder": _cancel_reminder,
    "check_email": _check_email,
    "enable_email_monitoring": _enable_email_monitoring,
    "disable_email_monitoring": _disable_email_monitoring,
    "get_calendar_events": _get_calendar_events,
    "create_calendar_event": _create_calendar_event,
    "cancel_calendar_event": _cancel_calendar_event,
    "enable_calendar_monitoring": _enable_calendar_monitoring,
    "disable_calendar_monitoring": _disable_calendar_monitoring,
}


# Deliberately narrow and exact-match, not a substring check — "stop the music" or
# "don't stop" must not trigger this, only an unambiguous, short exit phrase on its own.
EXIT_PHRASES = {"stop", "goodbye", "bye", "exit", "quit", "leave", "leave alexis"}


def _is_exit_request(text: str) -> bool:
    return text.strip().lower().rstrip("!.,? ") in EXIT_PHRASES


def execute_tool(tool_call: dict[str, Any]) -> tuple[str, bool]:
    name = tool_call["name"]
    args = tool_call["arguments"]

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        logger.warning("No handler registered for tool %r", name)
        return "Something went wrong executing that action.", True

    return handler(args)


# Safety cap on how many tool calls one turn can chain through, so a confused model
# can't loop indefinitely (and burn through the daily token budget doing it). Was 5,
# which was plenty before GUI control existed (most chains were 1-2 calls) but is
# tight for a click-heavy task -- e.g. opening an app plus several digit/operator
# clicks for a calculation can need 6+ steps on its own.
MAX_AGENT_STEPS = 12

# After a recovery step opens an app (e.g. Spotify wasn't running), most GUI apps
# genuinely aren't ready to use for a few seconds -- retrying the original action
# immediately would likely just fail again with the same error. This is a blind
# wait, not a poll for actual readiness, since there's no generic way to know when
# an arbitrary app has finished starting.
APP_LAUNCH_SETTLE_SECONDS = 5

# A tool's direct-reply result is treated as final immediately (no extra Groq call)
# unless it looks like it failed in a way the model might actually be able to fix —
# e.g. "play some music" failing because Spotify isn't open yet, where the fix is
# to open it and retry. This is what makes most single-tool turns just as cheap as
# before, while still allowing genuine multi-step chains when something goes wrong.
# Heuristic, not perfect: worst case on a miss is falling back to today's behavior
# (stop and speak the result), never something worse.
_PROBLEM_PHRASES = (
    "i couldn't", "i can't", "i wasn't able", "error", "failed", "please open",
    "not found", "no active", "isn't set up", "isn't running", "trouble",
)


def _looks_like_a_problem(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _PROBLEM_PHRASES)


def _run_agent_loop(
    messages: list[dict],
    recovering: bool = False,
    gui_confirmed: bool = False,
    start_step: int = 0,
) -> dict[str, Any]:
    """The actual multi-step tool-calling loop. Factored out of _route_new_request
    so a confirmation pause can RESUME it afterward instead of restarting from
    scratch — previously, confirming a gated action executed just that one tool
    and stopped, silently truncating any multi-step plan (e.g. clicking through a
    calculation) to only its first action, no matter how many more steps the
    model still intended to take.

    gui_confirmed tracks whether the user has already approved a click/type/
    submit-key action once THIS turn (see GUI_ACTION_TOOLS/_is_gui_action) --
    once true, later actions in that same family skip asking again, since
    re-confirming every single click in one task is pure friction once the
    user has approved the task itself. A different, unrelated confirmation-
    required tool appearing mid-chain still asks normally regardless.
    """
    for _step in range(start_step, MAX_AGENT_STEPS):
        message, error = chat_completion(messages, tools=TOOLS)
        if message is None:
            return {"action": "reply", "text": error, "pending_confirmation": None}

        if not message.tool_calls:
            reply = message.content or ""
            if not reply.strip():
                reply = "I'm not sure how to respond to that."
            return {"action": "reply", "text": reply, "pending_confirmation": None}

        call = message.tool_calls[0]
        args = json.loads(call.function.arguments)
        tool_call = {"name": call.function.name, "arguments": args}

        if tool_call["name"] == "end_conversation":
            result_text, _ = execute_tool(tool_call)
            return {"action": "exit", "text": result_text, "pending_confirmation": None}

        skip_confirmation = gui_confirmed and _is_gui_action(tool_call)
        if _requires_confirmation(tool_call) and not skip_confirmation:
            question = _describe_pending_action(tool_call)
            return {
                "action": "reply",
                "text": question,
                "pending_confirmation": {
                    "tool_call": tool_call,
                    "raw_call_id": call.id,
                    "raw_call_arguments": call.function.arguments,
                    "assistant_content": message.content,
                    "resume_messages": messages,
                    "recovering": recovering,
                    "gui_confirmed": gui_confirmed,
                    "step": _step,
                },
            }

        result_text, is_direct_reply = execute_tool(tool_call)

        if _is_gui_action(tool_call):
            gui_confirmed = True

        if _looks_like_a_problem(result_text):
            recovering = True

        if is_direct_reply and not recovering:
            return {"action": "reply", "text": result_text, "pending_confirmation": None}

        if recovering and tool_call["name"] == "open_app":
            time.sleep(APP_LAUNCH_SETTLE_SECONDS)

        # Something worth reasoning further about: feed the tool's result back and
        # let the model decide whether to try a different action or give up and
        # explain — that decision is what turns "play music" -> failure -> silence
        # into "play music" -> failure -> open Spotify -> wait -> retry -> success.
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [{
                "id": call.id, "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }],
        })
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result_text})

    logger.warning("Agent loop hit MAX_AGENT_STEPS (%d) without a final answer.", MAX_AGENT_STEPS)
    return {
        "action": "reply",
        "text": "That ended up needing more steps than I can handle right now.",
        "pending_confirmation": None,
    }


def _route_new_request(user_text: str, history: list[dict]) -> dict[str, Any]:
    messages = [_build_system_prompt()] + history + [{"role": "user", "content": user_text}]
    return _run_agent_loop(messages)


def route(
    user_text: str,
    history: list[dict] | None = None,
    pending_confirmation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if history is None:
        history = []

    if pending_confirmation is not None:
        if _is_exit_request(user_text):
            # An unambiguous "stop"/"goodbye" here must end the conversation, not get
            # fed to the confirmation classifier — which could easily misread "stop"
            # as declining the pending action (a "no") and then keep listening,
            # swallowing the user's actual intent to leave.
            return {"action": "exit", "text": "Okay, let me know if you need me.", "pending_confirmation": None}

        tool_call = pending_confirmation["tool_call"]
        question = _describe_pending_action(tool_call)
        decision = _classify_confirmation(question, user_text)

        if decision == "yes":
            result_text, is_direct_reply = execute_tool(tool_call)

            messages = pending_confirmation["resume_messages"]
            messages.append({
                "role": "assistant",
                "content": pending_confirmation["assistant_content"],
                "tool_calls": [{
                    "id": pending_confirmation["raw_call_id"], "type": "function",
                    "function": {
                        "name": tool_call["name"],
                        "arguments": pending_confirmation["raw_call_arguments"],
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": pending_confirmation["raw_call_id"],
                "content": result_text,
            })

            recovering = pending_confirmation["recovering"] or _looks_like_a_problem(result_text)
            gui_confirmed = pending_confirmation["gui_confirmed"] or _is_gui_action(tool_call)

            if is_direct_reply and not recovering:
                return {"action": "reply", "text": result_text, "pending_confirmation": None}

            return _run_agent_loop(
                messages, recovering=recovering, gui_confirmed=gui_confirmed,
                start_step=pending_confirmation["step"] + 1,
            )

        if decision == "no":
            return {"action": "reply", "text": "Okay, I won't do that.", "pending_confirmation": None}

        # "unclear" — the user didn't actually answer the question (changed the
        # subject, asked something else). Drop the pending action rather than get
        # stuck re-asking, and handle what they actually said as a fresh request.
        logger.info("Confirmation reply was unclear; dropping pending action and routing normally.")
        return _route_new_request(user_text, history)

    return _route_new_request(user_text, history)
