"""Зовнішні інструменти мають запускатися тихо.

Застосунок віконний, а ffmpeg і ffprobe — консольні: без спеціального
прапорця Windows відкриває для кожного виклику чорне вікно на частку секунди.
На додаванні одного відео таких викликів десятки, і виглядає це так, ніби
щось ламається.

Прапорець легко забути при новому виклику, тому перевіряється не поведінка
конкретного місця, а те, що інших місць немає.
"""

import re
import subprocess
import sys
from pathlib import Path

from backend.app.ingest import media_tools

BACKEND = Path(__file__).resolve().parents[1] / "backend"
ALLOWED = {"media_tools.py"}

_DIRECT_CALL = re.compile(r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b")


def test_external_tools_run_only_through_one_place():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        if path.name in ALLOWED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _DIRECT_CALL.search(line):
                offenders.append(f"{path.relative_to(BACKEND)}:{number}")

    assert not offenders, (
        "Ці виклики йдуть повз media_tools.run/popen і блиматимуть консоллю: "
        + ", ".join(offenders)
    )


def test_no_window_flag_is_set_on_windows():
    flags = media_tools._no_window_flags()
    if sys.platform == "win32":
        assert flags == subprocess.CREATE_NO_WINDOW
    else:
        assert flags == 0


def test_runner_keeps_output_and_does_not_raise():
    # Решта коду покладається саме на це: читає stderr і сама вирішує,
    # що робити з ненульовим кодом.
    result = media_tools.run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert result.returncode == 3
    assert result.stdout == ""
