"""FastAPI application for the XAUUSD Pure Price Action Replay Terminal.

Scope (SPEC-PA-REPLAY-01):
  * Serve the single-screen replay workstation (`index.html`).
  * Expose the replay catalogue/data API (`src.assistant.replay_api`).
  * Expose MT5 terminal connectivity for broker status only.

Everything related to the live signal bot — WebSocket streaming, SMC snapshots,
setup cards, and the SQLite journal — was removed in T-PAR-03. The replay
terminal replays historical bars; it never subscribes to live ticks.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.assistant.mt5_bridge import MT5Bridge
from src.assistant.replay_api import router as replay_router

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"
_INDEX_HTML = _TEMPLATES_DIR / "index.html"


class NoCacheStaticFiles(StaticFiles):
    """Serve dashboard assets with revalidation so edits show up immediately.

    The UI is a local, single-user dashboard: a stale cached chart.js after an
    update is a real failure mode, and the payloads are tiny.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """One MT5 session per server process."""
    bridge: MT5Bridge = app.state.mt5
    logger.info("replay terminal ready")
    try:
        yield
    finally:
        bridge.shutdown()  # detach MT5 cleanly when the server stops


def create_app() -> FastAPI:
    app = FastAPI(
        title="XAUUSD Replay Terminal",
        version="1.0.0",
        description="Pure price action historical replay (SPEC-PA-REPLAY-01)",
        lifespan=lifespan,
    )
    app.state.mt5 = MT5Bridge()
    # A month of M5 candles is ~640 KB of JSON that is 99% repeated float text.
    # Gzip takes it to ~80 KB; the browser decompresses transparently, so the
    # chart still receives the same untouched 3-decimal prices.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.mount("/static", NoCacheStaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(replay_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/mt5/status")
    def mt5_status() -> dict[str, Any]:
        return app.state.mt5.get_status()

    @app.post("/api/mt5/connect")
    def mt5_connect() -> dict[str, Any]:
        bridge: MT5Bridge = app.state.mt5
        ok = bridge.initialize()
        message = (
            "Terhubung ke MT5." if ok else (bridge.last_error or "Koneksi MT5 gagal.")
        )
        return {"ok": ok, "message": message, "status": bridge.get_status()}

    @app.post("/api/mt5/disconnect")
    def mt5_disconnect() -> dict[str, Any]:
        bridge: MT5Bridge = app.state.mt5
        bridge.shutdown()
        return {
            "ok": True,
            "message": "Koneksi MT5 diputus.",
            "status": bridge.get_status(),
        }

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_INDEX_HTML)

    return app


app = create_app()
