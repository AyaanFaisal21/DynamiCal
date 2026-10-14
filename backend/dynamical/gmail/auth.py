"""Gmail OAuth. Read-only scope. The token is stored next to the client secret."""

from __future__ import annotations

import json
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailAuthError(RuntimeError):
    pass


def load_credentials(credentials_path: Path, token_path: Path, *, interactive: bool = True):
    """Return valid Google credentials, refreshing or running the browser flow as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, json.JSONDecodeError):
            creds = None

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds, token_path)
            return creds
        except Exception:
            creds = None  # fall through to a fresh login

    if not interactive:
        raise GmailAuthError("No valid Gmail token. Run `dynamical auth` once to sign in.")
    if not credentials_path.exists():
        raise GmailAuthError(
            f"Missing OAuth client file at {credentials_path}. "
            "Create a Desktop OAuth client in Google Cloud and save it there. See README."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save(creds, token_path)
    return creds


def _save(creds, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
