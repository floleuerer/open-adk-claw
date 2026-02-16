from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


def _load_credentials(credentials_file: str, token_file: Path) -> Credentials:
    """Load or create OAuth2 credentials, persisting the refresh token."""
    creds: Credentials | None = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail OAuth token")
            creds.refresh(Request())
        else:
            logger.info("Starting OAuth2 consent flow for Gmail/Calendar")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        logger.info("OAuth token saved to %s", token_file)

    return creds


def get_gmail_service(credentials_file: str, token_file: Path) -> Resource:
    """Build and return an authenticated Gmail API service."""
    creds = _load_credentials(credentials_file, token_file)
    return build("gmail", "v1", credentials=creds)


def get_calendar_service(credentials_file: str, token_file: Path) -> Resource:
    """Build and return an authenticated Google Calendar API service."""
    creds = _load_credentials(credentials_file, token_file)
    return build("calendar", "v3", credentials=creds)
