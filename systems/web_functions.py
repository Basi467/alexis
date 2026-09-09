import logging
import webbrowser
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def open_website(site: str) -> str:
    site = site.strip().lower()

    if not site.startswith("http"):
        if "." not in site:
            site = f"{site}.com"
        site = f"https://{site}"

    try:
        webbrowser.open(site)
        return f"Opening {site}."
    except Exception as e:
        logger.error("Failed to open website %r: %s", site, e)
        return f"I couldn't open that website: {e}"


def open_gmail() -> str:
    """Dedicated tool so 'open my email'/'open gmail' reliably opens Gmail in the
    browser -- without this, the LLM's next-best guess was open_app, which found
    Outlook installed (a native desktop mail client) and launched that instead,
    even though the user has no Gmail desktop app and wants the web inbox."""
    try:
        webbrowser.open("https://mail.google.com/mail/u/0/#inbox")
        return "Opening Gmail."
    except Exception as e:
        logger.error("Failed to open Gmail: %s", e)
        return f"I couldn't open Gmail: {e}"


def search_web(query: str) -> str:
    try:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        webbrowser.open(url)
        return f"Here's what I found for {query}."
    except Exception as e:
        logger.error("Failed to search web for %r: %s", query, e)
        return f"I couldn't search for that: {e}"
