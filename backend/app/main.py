"""Точка входу: FastAPI на локальному порту + системне вебв'ю поверх нього."""

from __future__ import annotations

import logging
import socket
import sys
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import settings_store
from .api.routes import router
from .config import get_settings
from .db import backup
from .db.connection import init_db
from .version import APP_VERSION
from .worker import queue

log = logging.getLogger(__name__)

# Вікно застосунку. Потрібне, щоб показати системний діалог вибору теки:
# інакше довелося б просити користувача вписувати шлях руками.
_window = None


def pick_folder(title: str = "Оберіть теку") -> str | None:
    """Системний діалог вибору теки. None — якщо скасували або вікна немає."""
    if _window is None:
        return None
    import webview

    chosen = _window.create_file_dialog(webview.FOLDER_DIALOG)
    return chosen[0] if chosen else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    settings_store.load()

    # Відновлення з копії робиться саме тут — до першого підключення до бази.
    if backup.apply_pending_restore():
        log.warning("Базу відновлено з резервної копії")

    init_db()
    backup.create_if_due()
    queue.start()

    # Ваги важать гігабайти, і перше ж завантаження блокує потік на десятки
    # секунд. Гріємо у фоні, щоб вікно відкрилося одразу.
    threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()

    log.info("media-library %s · бібліотека: %s", APP_VERSION, settings.db_path)
    yield
    queue.stop()


def _warm_up() -> None:
    from .ml.registry import warm_up

    try:
        warm_up()
        log.info("Моделі завантажено")
    except Exception:
        log.exception("Не вдалося завантажити моделі")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="media-library", lifespan=lifespan)
    app.include_router(router)

    frontend = settings.frontend_dir
    if frontend.exists():
        assets = frontend / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            # Будь-який невідомий шлях віддає index.html — маршрутизація на клієнті.
            candidate = frontend / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")
    else:
        log.warning("Фронтенд не зібрано: %s не існує", frontend)

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

    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    # Порт випадковий, тож без цього рядка немає як ані перевірити застосунок
    # ззовні, ані зрозуміти з логу, що саме він слухав.
    log.info("Інтерфейс: http://127.0.0.1:%d", port)

    global _window
    _window = webview.create_window(
        "media-library",
        f"http://127.0.0.1:{port}",
        width=1400,
        height=900,
        min_size=(940, 620),
        background_color="#08090b",
    )
    webview.start()
    server.should_exit = True


def _setup_logging() -> None:
    """Лог у файл поруч із бібліотекою, плюс stdout, якщо він є.

    У віконному режимі stdout може бути відсутній або не вміти кирилицю
    (Windows віддає cp1252), і тоді кожен україномовний запис перетворюється
    на UnicodeEncodeError, який ховає справжню помилку. Файл у UTF-8 — єдине
    місце, де видно, що насправді сталося.
    """
    settings = get_settings()
    settings.ensure_dirs()

    handlers: list[logging.Handler] = [
        logging.FileHandler(settings.data_dir / "app.log", encoding="utf-8")
    ]
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def main() -> None:
    _setup_logging()
    run()


if __name__ == "__main__":
    main()
