"""Чи з'являються консольні вікна під час роботи застосунку.

Блимання консолі — симптом, який видно оком, але на слово покладатися не
варто: воно триває частку секунди й легко здається то зниклим, то присутнім.
Тут воно міряється: фоновий опитувач фіксує появу процесів, які тягнуть за
собою вікно консолі, поки застосунок виконує роботу.

  python scripts/check_console_flash.py <порт>
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# conhost — це і є вікно консолі; решта запускається нашим кодом.
WATCHED = ("conhost", "ffmpeg", "ffprobe", "cmd", "powershell")

POLL_SECONDS = 0.05


def snapshot() -> set[tuple[str, int]]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process " + ",".join(WATCHED) + " -EA SilentlyContinue "
         "| Select-Object Name,Id | ConvertTo-Json -Compress"],
        capture_output=True, text=True, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return set()
    if isinstance(data, dict):
        data = [data]
    return {(item["Name"], item["Id"]) for item in data}


class Watcher(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.seen: set[tuple[str, int]] = set()
        self.baseline = snapshot()

    def run(self) -> None:
        while not self.stop.is_set():
            self.seen |= snapshot() - self.baseline
            time.sleep(POLL_SECONDS)


def call(base: str, method: str, path: str, payload=None):
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        body = response.read()
    return json.loads(body) if body else None


def upload(base: str, paths: list[Path]):
    boundary = "----flash"
    parts: list[bytes] = []
    for path in paths:
        parts += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode(),
            path.read_bytes(),
            b"\r\n",
        ]
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{base}/items/upload", data=b"".join(parts), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def main() -> None:
    base = f"http://127.0.0.1:{sys.argv[1]}/api"
    watcher = Watcher()
    print(f"тлом уже запущено: {len(watcher.baseline)} процесів зі списку")
    watcher.start()

    print("\n1. Додаю відео — найважчий випадок: метадані, пошук сцен, кожен кадр")
    created = upload(base, [ROOT / "samples/audio/30.mp4"])
    item_id = created[0].get("item_id")
    while True:
        runtime = call(base, "GET", "/runtime")
        if runtime["jobs_running"] + runtime["jobs_queued"] == 0:
            break
        time.sleep(0.5)

    print("2. Зберігаю з прибиранням шуму")
    if item_id:
        call(base, "POST", f"/items/{item_id}/export", {"denoise": True})

    time.sleep(1.0)
    watcher.stop.set()
    watcher.join(timeout=2)

    print()
    if watcher.seen:
        print("ЗНАЙДЕНО консольні процеси:")
        for name, pid in sorted(watcher.seen):
            print(f"  {name} (pid {pid})")
        print("\nЗначить, щось запускається повз media_tools.run/popen.")
        raise SystemExit(1)

    print("Консольних процесів не з'являлося — блимати нема чому.")


if __name__ == "__main__":
    main()
