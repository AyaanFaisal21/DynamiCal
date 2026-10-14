"""FastAPI application factory. Serves the API and, when built, the web app."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import ROOT, Settings, get_settings
from ..db import Database
from ..llm import get_backend
from .routes import router

log = logging.getLogger("dynamical")
_UNSET = object()
FRONTEND_DIST = ROOT / "frontend" / "dist"


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    backend=_UNSET,
    *,
    background: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    if db is None:
        db = Database.from_path(settings.db_path)
    db.create_all()
    if backend is _UNSET:
        backend = get_backend(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if background and settings.sync_interval_minutes > 0:
            task = asyncio.create_task(_periodic_sync(app, settings.sync_interval_minutes))
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="DynamiCal", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.backend = backend
    app.include_router(router, prefix="/api")
    _mount_frontend(app, FRONTEND_DIST)
    return app


async def _periodic_sync(app: FastAPI, interval_minutes: int) -> None:
    from ..gmail.auth import GmailAuthError
    from ..gmail.sync import sync_gmail

    while True:
        try:
            report = await asyncio.to_thread(
                sync_gmail, app.state.db, app.state.settings, app.state.backend, log=lambda *_: None
            )
            log.info("background sync: %s", report.summary())
        except GmailAuthError as exc:
            log.warning("background sync skipped: %s", exc)
        except Exception:  # keep the loop alive
            log.exception("background sync failed")
        await asyncio.sleep(interval_minutes * 60)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.exists():
        return
    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = dist / path
        if path and candidate.is_file() and candidate.resolve().is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)
