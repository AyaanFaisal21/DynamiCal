"""Command line entry point: auth, sync, ingest, serve, status, init-db."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import get_settings
from .db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dynamical", description="A calendar that fills itself from email.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="sign in to Gmail once")

    p_sync = sub.add_parser("sync", help="fetch new mail and update the calendar")
    p_sync.add_argument("--days", type=int, help="look back this many days on a full query")
    p_sync.add_argument("--max", type=int, dest="max_messages", help="cap on messages per full query")
    p_sync.add_argument("--full", action="store_true", help="ignore the saved history point")
    p_sync.add_argument("--pending", action="store_true", help="only retry emails that waited for a model")

    p_ingest = sub.add_parser("ingest", help="run the pipeline on .eml files")
    p_ingest.add_argument("files", nargs="+", type=Path)
    p_ingest.add_argument("--label", action="append", default=[], help="Gmail label to attach, repeatable")
    p_ingest.add_argument("--reprocess", action="store_true")

    p_serve = sub.add_parser("serve", help="start the API and web app")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--reload", action="store_true")

    sub.add_parser("status", help="show counts and the last sync")
    sub.add_parser("init-db", help="create the database")

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "dynamical.api.app:create_app",
            factory=True,
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=args.reload,
        )
        return 0

    db = Database.from_path(settings.db_path)
    db.create_all()

    if args.command == "init-db":
        print(f"database ready at {settings.db_path}")
        return 0

    if args.command == "auth":
        from .gmail.auth import GmailAuthError, load_credentials

        try:
            load_credentials(settings.gmail_credentials, settings.gmail_token, interactive=True)
        except GmailAuthError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"signed in. token saved to {settings.gmail_token}")
        return 0

    from .llm import get_backend

    backend = get_backend(settings)
    if backend is None:
        print(f"note: no model available (LLM_PROVIDER={settings.llm_provider}). Only calendar attachments will be processed.")

    if args.command == "status":
        from .status import collect_status

        print(json.dumps(collect_status(db, settings, backend), indent=2))
        return 0

    if args.command == "ingest":
        from .gmail.parse import parse_eml_file
        from .ingest.pipeline import Pipeline

        mails = [parse_eml_file(path, labels=args.label) for path in args.files]
        report = Pipeline(db, settings, backend).ingest(mails, reprocess=args.reprocess)
        print(report.summary())
        for note in report.notes:
            print(" -", note)
        return 0

    if args.command == "sync":
        from .gmail.auth import GmailAuthError
        from .gmail.sync import sync_gmail
        from .ingest.pipeline import Pipeline

        if args.pending:
            report = Pipeline(db, settings, backend).process_pending()
        else:
            try:
                report = sync_gmail(db, settings, backend, days=args.days, max_messages=args.max_messages, full=args.full)
            except GmailAuthError as exc:
                print(exc, file=sys.stderr)
                return 1
        print(report.summary())
        for note in report.notes:
            print(" -", note)
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
