"""Готує ваги до збірки: зберігає ембедери у fp16 поруч, у власному форматі.

SigLIP2-large у fp32 важить 3.5 ГБ, E5 — 1.1 ГБ. Рахуємо ми їх на відеокарті,
де fp16 нативний, тож половинна точність зрізає ~2.3 ГБ зі збірки, не змінюючи
результатів пошуку помітно.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch  # noqa: E402
from transformers import AutoModel, AutoProcessor, AutoTokenizer  # noqa: E402

from backend.app.config import get_settings  # noqa: E402
from backend.app.ml.embedders import IMAGE_MODEL, TEXT_MODEL  # noqa: E402


def convert(repo_id: str, target: Path, with_processor: bool) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    cache = get_settings().models_dir
    model = AutoModel.from_pretrained(repo_id, cache_dir=cache, dtype=torch.float16)
    model.save_pretrained(target, safe_serialization=True)

    if with_processor:
        AutoProcessor.from_pretrained(repo_id, cache_dir=cache).save_pretrained(target)
    else:
        AutoTokenizer.from_pretrained(repo_id, cache_dir=cache).save_pretrained(target)

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1e9
    print(f"  {repo_id} -> {target.name}  ({size:.2f} ГБ)")


def main() -> None:
    local = get_settings().data_dir / "models" / "local"
    local.mkdir(parents=True, exist_ok=True)
    print("Конвертація у fp16:")
    convert(IMAGE_MODEL, local / "siglip", with_processor=True)
    convert(TEXT_MODEL, local / "e5", with_processor=False)


if __name__ == "__main__":
    main()
