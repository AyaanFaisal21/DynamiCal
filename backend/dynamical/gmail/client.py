"""Thin wrapper over the Gmail REST API.

Only three calls matter: list message ids for a query, fetch one message in
raw RFC 822 form, and list history since a known point for incremental sync.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field


@dataclass
class RawMessage:
    id: str
    thread_id: str
    raw: bytes
    labels: list[str] = field(default_factory=list)
    internal_date_ms: int = 0


class HistoryExpired(RuntimeError):
    """Gmail no longer has history from the stored id. Do a full sync."""


class GmailClient:
    def __init__(self, credentials):
        from googleapiclient.discovery import build

        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def profile(self) -> dict:
        return self._service.users().getProfile(userId="me").execute()

    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < max_results:
            response = (
                self._service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=min(100, max_results - len(ids)),
                    pageToken=page_token,
                )
                .execute()
            )
            ids.extend(m["id"] for m in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return ids[:max_results]

    def fetch_raw(self, message_id: str) -> RawMessage:
        data = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="raw")
            .execute()
        )
        raw = base64.urlsafe_b64decode(data["raw"].encode("ascii"))
        return RawMessage(
            id=data["id"],
            thread_id=data.get("threadId", ""),
            raw=raw,
            labels=list(data.get("labelIds", [])),
            internal_date_ms=int(data.get("internalDate", 0)),
        )

    def added_since(self, start_history_id: str) -> tuple[list[str], str | None]:
        """Message ids added since `start_history_id`, plus the newest history id."""
        from googleapiclient.errors import HttpError

        ids: list[str] = []
        newest: str | None = None
        page_token = None
        while True:
            try:
                response = (
                    self._service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=start_history_id,
                        historyTypes=["messageAdded"],
                        pageToken=page_token,
                    )
                    .execute()
                )
            except HttpError as exc:
                if exc.resp.status == 404:
                    raise HistoryExpired(start_history_id) from exc
                raise
            newest = response.get("historyId", newest)
            for record in response.get("history", []):
                for added in record.get("messagesAdded", []):
                    message = added.get("message", {})
                    labels = message.get("labelIds", [])
                    if "DRAFT" in labels or "SPAM" in labels or "TRASH" in labels:
                        continue
                    ids.append(message["id"])
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        # Preserve order, drop duplicates.
        return list(dict.fromkeys(ids)), newest
