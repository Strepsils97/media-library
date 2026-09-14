"""Точка входу: FastAPI на локальному порту + системне вебв'ю поверх нього."""

from __future__ import annotations

import logging
import socket
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db.connection import init_db

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    log.info("Бібліотека готова: %s", settings.db_path)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="media-library", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "data_dir": str(settings.data_dir),
            "db": settings.db_path.exists(),
        }

    frontend = settings.frontend_dir
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            # Будь-який невідомий шлях віддає index.html — маршрутизація на клієнті.
            candidate = frontend / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    return app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run() -> None:
    """Запускає сервер у фоновому потоці й відкриває вікно."""
    import webview

    port = _free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    webview.create_window(
        "media-library",
        f"http://127.0.0.1:{port}",
        width=1400,
        height=900,
        min_size=(900, 600),
    )
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
