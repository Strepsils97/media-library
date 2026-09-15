"""Резервні копії бази.

Копіюється саме база, а не вся бібліотека. Оригінали медіа можуть важити
сотні гігабайтів, і робити їх дублікати при кожному запуску було б і довго,
і марно — це просто файли, які користувач може скопіювати сам. А от база
зберігає всю роботу, якої в файлах немає: теги, виправлені транскрипції,
лейбли, вектори. Її втрата означає переіндексацію всієї бібліотеки й
безповоротну втрату ручних правок.

Копія знімається через власний механізм SQLite, а не копіюванням файлу.
Файл бази під WAL у будь-яку мить може бути неузгоджений сам із собою, тож
`shutil.copy` дав би копію, яка не відкриється саме тоді, коли знадобиться.

Відновлення не робиться на живій базі: обраний файл лише позначається, а
підміна відбувається на наступному старті, до першого підключення.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..config import get_settings

log = logging.getLogger(__name__)

# Скільки копій тримати. Кожна важить як сама база.
KEEP = 5

# Як часто знімати копію при старті.
INTERVAL = timedelta(hours=24)

_PENDING = "restore-pending.db"
# Поруч із копією лежить ім'я тієї, з якої її зроблено: інакше в інтерфейсі
# нічого було б показати, крім службової назви службового файлу.
_PENDING_SOURCE = "restore-pending.source"
_REPLACED = "replaced-before-restore.db"


@dataclass(frozen=True, slots=True)
class Backup:
    name: str
    path: Path
    created_at: str
    size_bytes: int
    reason: str


def _dir() -> Path:
    path = get_settings().data_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse(path: Path) -> Backup:
    # library-20260915-1204-startup.db
    parts = path.stem.split("-")
    stamp, reason = "", "невідомо"
    if len(parts) >= 3:
        try:
            stamp = (
                datetime.strptime(f"{parts[1]}-{parts[2]}", "%Y%m%d-%H%M%S%f")
                .replace(tzinfo=UTC)
                .isoformat()
            )
        except ValueError:
            stamp = ""
        reason = "-".join(parts[3:]) or "невідомо"
    stat = path.stat()
    return Backup(
        name=path.name,
        path=path,
        created_at=stamp or datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        size_bytes=stat.st_size,
        reason=reason,
    )


def listing() -> list[Backup]:
    """Копії, найсвіжіші першими."""
    backups = [_parse(p) for p in _dir().glob("library-*.db")]
    return sorted(backups, key=lambda b: b.created_at, reverse=True)


def verify(path: Path) -> bool:
    """Чи копія взагалі відкривається й не пошкоджена."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("Копія %s не пройшла перевірку: %s", path.name, exc)
        return False


def create(reason: str = "manual") -> Backup | None:
    """Знімає копію бази. Повертає None, якщо бази ще немає."""
    settings = get_settings()
    if not settings.db_path.exists():
        return None

    from .connection import get_connection

    # З мікросекундами: дві копії в межах однієї секунди — не крайній
    # випадок, а звичайна справа під час міграції або в тестах.
    now = datetime.now(UTC)
    stamp = f"{now:%Y%m%d-%H%M%S}{now.microsecond // 1000:03d}"
    safe_reason = "".join(c for c in reason if c.isalnum() or c in "-_") or "manual"
    target = _dir() / f"library-{stamp}-{safe_reason}.db"

    destination = sqlite3.connect(target)
    try:
        # Механізм SQLite знімає узгоджений знімок навіть із бази, у яку
        # просто зараз пишуть. Копіювання файлу такої гарантії не дає.
        get_connection().backup(destination)
    finally:
        destination.close()

    if not verify(target):
        target.unlink(missing_ok=True)
        log.error("Свіжа копія не пройшла перевірку — видалено")
        return None

    prune()
    backup = _parse(target)
    log.info(
        "Копію збережено: %s (%.1f МБ, привід: %s)",
        backup.name, backup.size_bytes / 1024**2, reason,
    )
    return backup


def prune(keep: int = KEEP) -> int:
    """Лишає лише найсвіжіші копії."""
    extra = listing()[keep:]
    for backup in extra:
        backup.path.unlink(missing_ok=True)
    return len(extra)


def create_if_due(reason: str = "startup") -> Backup | None:
    """Знімає копію, якщо від останньої минуло досить часу."""
    latest = listing()
    if latest:
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(latest[0].created_at)
            if age < INTERVAL:
                return None
        except ValueError:
            pass
    return create(reason)


def schedule_restore(name: str) -> Path:
    """Позначає копію до відновлення. Підміна станеться на наступному старті.

    Живу базу підміняти не можна: у неї відкриті підключення, а поруч лежать
    журнали WAL, які до неї не підійдуть. Тому файл лише кладеться поруч, а
    заміна відбувається до першого підключення.
    """
    source = _dir() / name
    if not source.exists():
        raise FileNotFoundError(f"Копії {name} не існує")
    if not verify(source):
        raise ValueError(f"Копія {name} пошкоджена — відновлювати з неї не можна")

    # Копіюємо, а не просто запам'ятовуємо назву: зайві копії видаляються
    # автоматично, і обрана могла б зникнути ще до перезапуску.
    data_dir = get_settings().data_dir
    pending = data_dir / _PENDING
    shutil.copy2(source, pending)
    (data_dir / _PENDING_SOURCE).write_text(name, encoding="utf-8")

    log.info("Відновлення з %s відбудеться при наступному запуску", name)
    return pending


def pending_restore() -> Path | None:
    path = get_settings().data_dir / _PENDING
    return path if path.exists() else None


def pending_restore_source() -> str | None:
    """Назва копії, з якої відбудеться відновлення."""
    if pending_restore() is None:
        return None
    marker = get_settings().data_dir / _PENDING_SOURCE
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip() or None
    return _PENDING


def cancel_restore() -> bool:
    path = pending_restore()
    if path is None:
        return False
    path.unlink(missing_ok=True)
    (get_settings().data_dir / _PENDING_SOURCE).unlink(missing_ok=True)
    return True


def apply_pending_restore() -> bool:
    """Підміняє базу позначеною копією. Викликати до першого підключення."""
    pending = pending_restore()
    if pending is None:
        return False

    settings = get_settings()
    db = settings.db_path

    source_name = pending_restore_source()
    marker = settings.data_dir / _PENDING_SOURCE

    if not verify(pending):
        pending.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        log.error("Позначена до відновлення копія пошкоджена — відновлення скасовано")
        return False

    # Поточну базу не видаляємо, а відкладаємо: якщо відновлення виявиться
    # помилкою, повернутися буде до чого.
    if db.exists():
        replaced = settings.data_dir / _REPLACED
        replaced.unlink(missing_ok=True)
        db.replace(replaced)

    # Журнали належать старій базі й новій не підійдуть.
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)

    pending.replace(db)
    marker.unlink(missing_ok=True)
    log.warning(
        "Базу відновлено з копії %s; попередня лежить у %s", source_name, _REPLACED
    )
    return True
