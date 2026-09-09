"""Shared OAuth credential handling for all Google API access (Gmail, Calendar,
and any future Google API this assistant uses). One combined scope list and one
cached token file -- Google issues a single token covering every scope requested
together, so adding Calendar didn't need a second login flow or a second app
registration, just a re-consent to cover the added scope.
"""
import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

_credentials = None


def is_configured() -> bool:
    return os.path.exists(GMAIL_CREDENTIALS_FILE)


def _has_all_scopes(creds) -> bool:
    granted = set(creds.scopes or [])
    return set(SCOPES).issubset(granted)


def get_credentials():
    """Returns valid OAuth credentials covering all of SCOPES, or None if not set
    up yet / auth failed. Cached at module level so repeated calls within one
    process don't redo the handshake. If a cached token exists but is missing a
    scope added later (e.g. Calendar added after Gmail was already set up), this
    forces a fresh interactive consent rather than silently running with
    insufficient permission -- a refresh token can't grant scopes it was never
    issued for."""
    global _credentials
    if _credentials is not None and _credentials.valid and _has_all_scopes(_credentials):
        return _credentials

    if not os.path.exists(GMAIL_CREDENTIALS_FILE):
        logger.warning("Google APIs not set up: %s not found.", GMAIL_CREDENTIALS_FILE)
        return None

    creds = None
    if os.path.exists(GMAIL_TOKEN_FILE):
        try:
            loaded = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), SCOPES)
            if _has_all_scopes(loaded):
                creds = loaded
            else:
                logger.info("Cached Google token is missing a required scope; re-authorizing.")
        except Exception as e:
            logger.warning("Could not load cached Google token: %s", e)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error("Failed to refresh Google token: %s", e)
                creds = None

        if not creds or not creds.valid:
            # Deliberately does NOT fall back to an interactive run_local_server()
            # flow here. This function is called from both voice-triggered tool
            # handlers and unattended scheduled tasks (email/calendar monitor,
            # the morning alarm) -- a refresh token going bad (which happens
            # automatically roughly every 7 days for a Google Cloud OAuth app
            # left in "Testing" publishing status, a Google policy limit, not a
            # bug) previously made every single one of those background runs
            # silently pop open a *new* browser tab asking for Google sign-in,
            # forever, since nothing was ever there to complete it. Confirmed
            # live: this fired from the email monitor and left a dangling
            # "Access blocked" tab. Re-authorizing is now a deliberate one-time
            # action the user runs themselves -- see the __main__ block below.
            logger.error(
                "Google token is invalid/expired and can't be silently refreshed. "
                "Run `python -m systems.google_auth` to re-authorize interactively."
            )
            return None

        try:
            with open(GMAIL_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except OSError as e:
            logger.warning("Could not cache Google token: %s", e)

    _credentials = creds
    return creds


def authorize_interactively() -> None:
    """Deliberate, manual (re)authorization -- run this yourself (`python -m
    systems.google_auth`) when Gmail/Calendar stop working. Never called
    automatically from anywhere else in the app; see get_credentials()."""
    global _credentials
    flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    with open(GMAIL_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    _credentials = creds
    print("Google authorization saved.")


if __name__ == "__main__":
    authorize_interactively()


def get_service(api_name: str, api_version: str):
    creds = get_credentials()
    if creds is None:
        return None
    try:
        return build(api_name, api_version, credentials=creds)
    except Exception as e:
        logger.error("Failed to build %s service: %s", api_name, e)
        return None
