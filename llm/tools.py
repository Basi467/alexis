DOCUMENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "Search the user's documents by meaning/content to find or answer questions about files — not for opening apps or system tasks. Use for requests like 'find me a doc about X', 'what does my resume say', 'get me the file about Y'.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in the user's documents."}
            },
            "required": ["query"]
        }
    }
}

OPEN_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "open_last_file",
        "description": "Open the most recently found document or file, when the user says things like 'open it', 'open that file', or 'open the document'.",
        "parameters": {"type": "object", "properties": {}}
    }
}

OPEN_APP_TOOL = {
    "type": "function",
    "function": {
        "name": "open_app",
        "description": "Open a known application on the user's computer, e.g. 'open chrome', 'open notepad'.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "The name of the application to open, e.g. 'chrome', 'notepad', 'spotify'."}
            },
            "required": ["app_name"]
        }
    }
}

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather.",
        "parameters": {"type": "object", "properties": {}}
    }
}

DATETIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_datetime",
        "description": "Get the current date and/or time.",
        "parameters": {"type": "object", "properties": {}}
    }
}

END_CONVERSATION_TOOL = {
    "type": "function",
    "function": {
        "name": "end_conversation",
        "description": "End the current conversation. ONLY call this if the user explicitly and unambiguously asks to stop, say goodbye, or leave — such as 'leave alexis', 'goodbye', 'stop'. Do not call this if there is any ambiguity.",
        "parameters": {"type": "object", "properties": {}}
    }
}
FIND_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "find_file_by_name",
        "description": "Find a file by its filename or a keyword likely in its filename, when the user names a specific file rather than describing its content or topic — e.g. 'find binance.txt', 'open my resume file'. Use search_documents instead if the user is describing what a document is about.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The filename or keyword to search for."}
            },
            "required": ["query"]
        }
    }
}
YOUTUBE_TOOL = {
    "type": "function",
    "function": {
        "name": "play_youtube",
        "description": "Search YouTube and open a video — for music, songs, or any video content the user wants to watch or listen to. Use for requests like 'play some music', 'play [song name]', 'find a video about X'.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for on YouTube."}
            },
            "required": ["query"]
        }
    }
}
SPOTIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "play_spotify",
        "description": "Play a song or track on Spotify. Use only when the user specifically mentions Spotify, or when YouTube isn't the clear intent.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The song or artist to play."}
            },
            "required": ["query"]
        }
    }
}
SPOTIFY_PAUSE_TOOL = {
    "type": "function",
    "function": {
        "name": "pause_spotify",
        "description": "Pause the currently playing Spotify track.",
        "parameters": {"type": "object", "properties": {}}
    }
}

SPOTIFY_RESUME_TOOL = {
    "type": "function",
    "function": {
        "name": "resume_spotify",
        "description": "Resume/unpause Spotify playback.",
        "parameters": {"type": "object", "properties": {}}
    }
}

SPOTIFY_SKIP_TOOL = {
    "type": "function",
    "function": {
        "name": "skip_spotify",
        "description": "Skip to the next track on Spotify.",
        "parameters": {"type": "object", "properties": {}}
    }
}
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web and open the results in a browser so the user can look through them visually. Use only when the user wants to browse it themselves ('open a search for X', 'look this up for me to see'). If they want you to actually answer using what's out there, use search_and_answer instead.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."}
            },
            "required": ["query"]
        }
    }
}
SEARCH_AND_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "search_and_answer",
        "description": "Search the web, read the actual page content, and answer the user's question using it -- for factual questions, research, or 'what is/who is/how does X' style requests where the user wants a spoken answer, not a browser tab opened.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for / the question to answer."}
            },
            "required": ["query"]
        }
    }
}
LIST_JOB_APPLICATIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_job_applications",
        "description": "List tracked job applications, optionally filtered by status or company. Use for questions like 'what's the status of my Amazon application', 'list my pending applications', 'how many places have I heard back from'. Applications are tracked automatically from job-related emails, plus anything the user reports manually.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": ["string", "null"], "description": "Optional filter: 'applied', 'interviewing', 'offer', 'rejected', or 'other'. Omit or use null to list everything."},
                "company": {"type": ["string", "null"], "description": "Optional: check just one specific company's application status instead of listing all. Omit or use null to list everything."}
            }
        }
    }
}
UPDATE_JOB_APPLICATION_TOOL = {
    "type": "function",
    "function": {
        "name": "update_job_application",
        "description": "Manually add or update a tracked job application -- use when the user tells you directly about an application, interview, offer, or rejection that wasn't caught from email, e.g. 'I applied to Meta for a backend role' or 'mark my Google application as rejected'.",
        "parameters": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "role": {"type": "string", "description": "The role/position, if known."},
                "status": {"type": "string", "description": "One of: applied, interviewing, offer, rejected, other."}
            },
            "required": ["company", "status"]
        }
    }
}
LOOK_AT_SCREEN_TOOL = {
    "type": "function",
    "function": {
        "name": "look_at_screen",
        "description": "Look at what's currently displayed on the user's screen right now and answer a question about it, or describe it. Use for 'what's on my screen', 'what does this say', 'read this for me', 'help me with this error', 'what am I looking at', or anything that needs seeing actual screen content rather than reasoning over text.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What to look for or answer about the screen. If the user just wants a general description, use something like 'Describe what's visible on the screen.'"
                }
            },
            "required": ["question"]
        }
    }
}
CLICK_ON_SCREEN_TOOL = {
    "type": "function",
    "function": {
        "name": "click_on_screen",
        "description": "Look at the screen, find a described element (a button, link, icon, field, menu item), and click it. Use for 'click X', 'press the Y button', 'select Z from the menu' -- anything that needs an actual mouse click on something visible. Only describe one specific element per call.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What to click, described the way you'd point it out to someone looking at the same screen, e.g. 'the blue Submit button' or 'the search icon in the top right'."}
            },
            "required": ["description"]
        }
    }
}
TYPE_TEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "type_text",
        "description": "Type text into whatever field currently has focus (e.g. after clicking into a search box or text field). Does not press Enter afterward -- use press_key for that separately.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The exact text to type."}
            },
            "required": ["text"]
        }
    }
}
PRESS_KEY_TOOL = {
    "type": "function",
    "function": {
        "name": "press_key",
        "description": "Press a single key or keyboard shortcut, e.g. 'enter', 'tab', 'esc', 'backspace', or a combo like 'ctrl+c', 'ctrl+v', 'alt+tab'.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key or hotkey combo to press, e.g. 'enter' or 'ctrl+c'."}
            },
            "required": ["key"]
        }
    }
}
SCROLL_SCREEN_TOOL = {
    "type": "function",
    "function": {
        "name": "scroll_screen",
        "description": "Scroll the current window up or down.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Positive to scroll up, negative to scroll down. Roughly 300-500 per 'page' worth of scrolling."}
            },
            "required": ["amount"]
        }
    }
}
OPEN_WEBSITE_TOOL = {
    "type": "function",
    "function": {
        "name": "open_website",
        "description": "Open a specific website in the browser, when the user names a site directly — e.g. 'open youtube.com', 'open github', 'go to linkedin'.",
        "parameters": {
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "The website name or URL to open, e.g. 'github.com' or 'linkedin'."}
            },
            "required": ["site"]
        }
    }
}
OPEN_GMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "open_gmail",
        "description": "Open the user's Gmail inbox in the browser. Use for 'open my email', 'open gmail', 'show me my inbox'. Do NOT use open_app for this -- the user has no Gmail desktop app installed and does not want a native mail client like Outlook opened.",
        "parameters": {"type": "object", "properties": {}}
    }
}
GET_CALENDAR_EVENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_calendar_events",
        "description": "Get the user's calendar events for a date or range of dates. Use for 'what's on my calendar today', 'do I have any meetings tomorrow', 'what's my schedule this week'.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date as YYYY-MM-DD, computed from the current date given in context and the user's phrasing (e.g. 'today', 'tomorrow')."},
                "days": {"type": "integer", "description": "How many days forward to include starting from start_date. Use 1 for a single day, 7 for a week. Defaults to 1.", "default": 1}
            },
            "required": ["start_date"]
        }
    }
}
CREATE_CALENDAR_EVENT_TOOL = {
    "type": "function",
    "function": {
        "name": "create_calendar_event",
        "description": "Add a new event to the user's calendar. Use for 'add an event', 'schedule a meeting', 'block my calendar for X'.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "The event title, e.g. 'Dentist appointment'."},
                "start_time": {"type": "string", "description": "Start date and time as 'YYYY-MM-DD HH:MM' in 24-hour time, computed from the current date/time given in context and the user's phrasing."},
                "end_time": {"type": "string", "description": "End date and time as 'YYYY-MM-DD HH:MM'. If the user doesn't specify a duration, default to 1 hour after start_time."}
            },
            "required": ["summary", "start_time", "end_time"]
        }
    }
}
CANCEL_CALENDAR_EVENT_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel_calendar_event",
        "description": "Cancel/remove an event from the user's calendar. Use for 'cancel my meeting with X', 'delete the dentist appointment'.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "What the event is about, e.g. 'dentist appointment' -- matched against upcoming event titles."}
            },
            "required": ["identifier"]
        }
    }
}
SET_ALARM_TOOL = {
    "type": "function",
    "function": {
        "name": "set_daily_alarm",
        "description": "Set or change the user's daily wake-up alarm time. Use for requests like 'wake me up at 7am' or 'change my alarm to 8'.",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "24-hour time in HH:MM format, e.g. '07:00' for 7am, '19:30' for 7:30pm."}
            },
            "required": ["time"]
        }
    }
}
SET_VOLUME_TOOL = {
    "type": "function",
    "function": {
        "name": "set_volume",
        "description": "Set the system volume to a specific level. Use for requests like 'set volume to 50' or 'turn the volume up to max'.",
        "parameters": {
            "type": "object",
            "properties": {
                "percent": {"type": "integer", "description": "Volume level from 0 to 100."}
            },
            "required": ["percent"]
        }
    }
}
MUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "mute_volume",
        "description": "Mute the system volume.",
        "parameters": {"type": "object", "properties": {}}
    }
}
UNMUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "unmute_volume",
        "description": "Unmute the system volume.",
        "parameters": {"type": "object", "properties": {}}
    }
}
SET_BRIGHTNESS_TOOL = {
    "type": "function",
    "function": {
        "name": "set_brightness",
        "description": "Set the screen brightness to a specific level. Use for requests like 'set brightness to 70' or 'dim the screen'.",
        "parameters": {
            "type": "object",
            "properties": {
                "percent": {"type": "integer", "description": "Brightness level from 0 to 100."}
            },
            "required": ["percent"]
        }
    }
}
CLOSE_APP_TOOL = {
    "type": "function",
    "function": {
        "name": "close_app",
        "description": "Close a running application. Use for requests like 'close chrome' or 'quit notepad'. This can lose unsaved work in that application.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "The name of the application to close, e.g. 'chrome', 'notepad'."}
            },
            "required": ["app_name"]
        }
    }
}
SWITCH_APP_TOOL = {
    "type": "function",
    "function": {
        "name": "switch_to_app",
        "description": "Bring an already-open application's window to the foreground. Use for requests like 'switch to chrome' or 'go to notepad'. Not for opening a new instance — use open_app for that.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "The name of the application to switch to, e.g. 'chrome', 'notepad'."}
            },
            "required": ["app_name"]
        }
    }
}
LOCK_COMPUTER_TOOL = {
    "type": "function",
    "function": {
        "name": "lock_computer",
        "description": "Lock the computer. Use for requests like 'lock my computer' or 'lock the screen'.",
        "parameters": {"type": "object", "properties": {}}
    }
}
RESTART_COMPUTER_TOOL = {
    "type": "function",
    "function": {
        "name": "restart_computer",
        "description": "Restart the computer. Only call this if the user explicitly and unambiguously asks to restart or reboot the computer.",
        "parameters": {"type": "object", "properties": {}}
    }
}
SHUTDOWN_COMPUTER_TOOL = {
    "type": "function",
    "function": {
        "name": "shutdown_computer",
        "description": "Shut down the computer. Only call this if the user explicitly and unambiguously asks to shut down or turn off the computer.",
        "parameters": {"type": "object", "properties": {}}
    }
}
CANCEL_SHUTDOWN_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel_shutdown",
        "description": "Cancel a pending restart or shutdown that was scheduled a few seconds ago. Use for 'cancel shutdown', 'stop the restart', 'don't shut down' right after one was requested.",
        "parameters": {"type": "object", "properties": {}}
    }
}

SET_REMINDER_TOOL = {
    "type": "function",
    "function": {
        "name": "set_reminder",
        "description": "Create a reminder for a specific message at a specific future date/time. Use for requests like 'remind me to check the oven in 20 minutes' or 'remind me every day at 8am to take my vitamins'. Not for the single daily wake-up alarm -- use set_daily_alarm for that.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to remind the user about, e.g. 'check the oven'."},
                "run_time": {"type": "string", "description": "The date and time to fire, as 'YYYY-MM-DD HH:MM' in 24-hour time. Compute this from the current date/time given in the system prompt and the user's relative phrasing (e.g. 'in 20 minutes', 'tomorrow at 3pm')."},
                "recurrence": {"type": "string", "enum": ["once", "daily"], "description": "'once' for a one-time reminder, 'daily' for something that repeats every day at that time."}
            },
            "required": ["message", "run_time", "recurrence"]
        }
    }
}
LIST_REMINDERS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": "List the user's currently scheduled reminders. Use for 'what reminders do I have' or 'do I have anything scheduled'.",
        "parameters": {"type": "object", "properties": {}}
    }
}
CANCEL_REMINDER_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel_reminder",
        "description": "Cancel an existing reminder. Use for 'cancel the oven reminder' or 'delete my vitamins reminder'.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "What the reminder is about, e.g. 'oven' or 'vitamins' -- matched against existing reminders' messages."}
            },
            "required": ["identifier"]
        }
    }
}

CHECK_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "check_email",
        "description": "Check the user's Gmail inbox for important unread emails -- especially job hiring, recruiting, interview, or job-offer related messages. Use for 'check my email', 'any important emails', 'did I get any interview requests'.",
        "parameters": {"type": "object", "properties": {}}
    }
}
ENABLE_EMAIL_MONITORING_TOOL = {
    "type": "function",
    "function": {
        "name": "enable_email_monitoring",
        "description": "Turn on background email monitoring, so the user is proactively told about important emails (job/interview related) as they arrive, without having to ask. Use for 'watch my email for me', 'let me know if I get an important email', 'start monitoring my inbox'.",
        "parameters": {"type": "object", "properties": {}}
    }
}
DISABLE_EMAIL_MONITORING_TOOL = {
    "type": "function",
    "function": {
        "name": "disable_email_monitoring",
        "description": "Turn off background email monitoring. Use for 'stop watching my email', 'turn off email monitoring'.",
        "parameters": {"type": "object", "properties": {}}
    }
}
ENABLE_CALENDAR_MONITORING_TOOL = {
    "type": "function",
    "function": {
        "name": "enable_calendar_monitoring",
        "description": "Turn on background calendar monitoring, so the user gets a spoken heads-up before upcoming events -- including ones not created via Alexis, like a meeting someone else invited them to. Use for 'watch my calendar for me', 'give me a heads up before my meetings', 'start monitoring my calendar'.",
        "parameters": {"type": "object", "properties": {}}
    }
}
DISABLE_CALENDAR_MONITORING_TOOL = {
    "type": "function",
    "function": {
        "name": "disable_calendar_monitoring",
        "description": "Turn off background calendar monitoring. Use for 'stop watching my calendar', 'turn off calendar monitoring'.",
        "parameters": {"type": "object", "properties": {}}
    }
}

ALL_TOOLS = [DOCUMENTS_TOOL, OPEN_FILE_TOOL, OPEN_APP_TOOL, WEATHER_TOOL, DATETIME_TOOL, END_CONVERSATION_TOOL,FIND_FILE_TOOL,YOUTUBE_TOOL,SPOTIFY_PAUSE_TOOL,SPOTIFY_RESUME_TOOL,SPOTIFY_SKIP_TOOL,SPOTIFY_TOOL,WEB_SEARCH_TOOL,SEARCH_AND_ANSWER_TOOL,LIST_JOB_APPLICATIONS_TOOL,UPDATE_JOB_APPLICATION_TOOL,LOOK_AT_SCREEN_TOOL,CLICK_ON_SCREEN_TOOL,TYPE_TEXT_TOOL,PRESS_KEY_TOOL,SCROLL_SCREEN_TOOL,OPEN_WEBSITE_TOOL,OPEN_GMAIL_TOOL,SET_ALARM_TOOL,
             SET_VOLUME_TOOL, MUTE_TOOL, UNMUTE_TOOL, SET_BRIGHTNESS_TOOL, CLOSE_APP_TOOL, SWITCH_APP_TOOL,
             LOCK_COMPUTER_TOOL, RESTART_COMPUTER_TOOL, SHUTDOWN_COMPUTER_TOOL, CANCEL_SHUTDOWN_TOOL,
             SET_REMINDER_TOOL, LIST_REMINDERS_TOOL, CANCEL_REMINDER_TOOL,
             CHECK_EMAIL_TOOL, ENABLE_EMAIL_MONITORING_TOOL, DISABLE_EMAIL_MONITORING_TOOL,
             GET_CALENDAR_EVENTS_TOOL, CREATE_CALENDAR_EVENT_TOOL, CANCEL_CALENDAR_EVENT_TOOL,
             ENABLE_CALENDAR_MONITORING_TOOL, DISABLE_CALENDAR_MONITORING_TOOL]