"""Read-only Gmail access, on top of the shared OAuth handling in
systems/google_auth.py. Scope is deliberately read-only (gmail.readonly) -- this
never sends, deletes, or modifies anything, only reads subjects/senders/bodies
to decide what's important.
"""
import base64
import logging
import re

from googleapiclient.errors import HttpError

from systems.google_auth import get_service, is_configured  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)

# Keeps prompt size/cost bounded -- far more informative than the ~150-char
# snippet this used to be limited to, without pulling in an entire quoted
# thread history or a huge HTML newsletter body.
MAX_BODY_CHARS = 2000


def _get_service():
    return get_service("gmail", "v1")


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_snippet(message: dict) -> str:
    return message.get("snippet", "")


def _decode_body_part(data: str) -> str:
    try:
        decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return decoded.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&#39;|&quot;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_body(payload: dict) -> str:
    """Walks a (possibly nested multipart) message payload for the best
    available body text -- prefers text/plain, falls back to a stripped
    text/html part if that's all the message has."""
    plain, html = None, None

    def walk(part: dict) -> None:
        nonlocal plain, html
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if mime_type == "text/plain" and body_data and plain is None:
            plain = _decode_body_part(body_data)
        elif mime_type == "text/html" and body_data and html is None:
            html = _decode_body_part(body_data)
        for sub_part in part.get("parts", []) or []:
            walk(sub_part)

    walk(payload)

    if plain:
        return plain.strip()
    if html:
        return _strip_html(html)
    return ""


def fetch_recent_emails(max_results: int = 10, unread_only: bool = True) -> list[dict]:
    """Returns a list of {id, sender, subject, snippet, body, date} dicts, most
    recent first. `body` is the decoded message text (plain preferred, HTML
    stripped as a fallback), truncated to MAX_BODY_CHARS -- classification and
    extraction used to work off only the ~150-char Gmail snippet, which missed
    detail buried past the first line. Returns an empty list (not an error) if
    Gmail isn't set up yet or the API call fails -- callers should treat "no
    emails" and "can't check right now" the same way: nothing to report."""
    service = _get_service()
    if service is None:
        return []

    try:
        query = "is:unread" if unread_only else ""
        result = service.users().messages().list(
            userId="me", maxResults=max_results, q=query
        ).execute()
        message_refs = result.get("messages", [])

        emails = []
        for ref in message_refs:
            msg = service.users().messages().get(
                userId="me", id=ref["id"], format="full",
            ).execute()
            payload = msg.get("payload", {})
            headers = payload.get("headers", [])
            emails.append({
                "id": msg["id"],
                "sender": _get_header(headers, "From"),
                "subject": _get_header(headers, "Subject"),
                "snippet": _decode_snippet(msg),
                "body": _extract_body(payload)[:MAX_BODY_CHARS],
                "date": _get_header(headers, "Date"),
            })
        return emails

    except HttpError as e:
        logger.error("Gmail API error: %s", e)
        return []
    except Exception as e:
        logger.error("Failed to fetch emails: %s", e)
        return []
