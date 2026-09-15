"""Готує ваги до збірки: локальні копії у половинній точності.

Ваги у fp32 важать удвічі більше, а рахуємо ми їх на відеокарті, де fp16
нативний. Замір (scripts/bench_precision.py) показав, що Recall@1, Recall@3
і MRR збігаються з fp32 до третього знака.

Заразом усе стягується саме в теку моделей застосунку: зібраний застосунок
працює офлайн, і будь-що, залишене в домашньому кеші HuggingFace, там просто
не знайдеться.
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
from backend.app.ml.embedders import IMAGE_MODELS, TEXT_MODEL  # noqa: E402


def size_gb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9


def convert_transformers(repo_id: str, target: Path, with_processor: bool) -> None:
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

    print(f"  {repo_id} -> {target.name}  ({size_gb(target):.2f} ГБ)")


def convert_open_clip(model_name: str, pretrained: str, target: Path) -> None:
    import open_clip

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    cache = str(get_settings().models_dir)
    model, _, _ = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained, cache_dir=cache
    )
    torch.save(model.half().state_dict(), target / "open_clip_pytorch_model.bin")

    # Токенізатор живе окремим завантаженням — прогріваємо кеш у теці моделей,
    # щоб офлайновій збірці не довелося по нього ходити в мережу.
    open_clip.get_tokenizer(model_name, cache_dir=cache)

    print(f"  {model_name} -> {target.name}  ({size_gb(target):.2f} ГБ)")


def main() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    local = settings.data_dir / "models" / "local"
    local.mkdir(parents=True, exist_ok=True)

    print("Конвертація у fp16:")
    convert_transformers(IMAGE_MODELS["image_a"], local / "siglip", with_processor=True)
    convert_open_clip(*IMAGE_MODELS["image_b"], local / "nllbclip")
    convert_transformers(TEXT_MODEL, local / "e5", with_processor=False)

    print(f"\nВсього в теці моделей: {size_gb(settings.data_dir / 'models'):.2f} ГБ")


if __name__ == "__main__":
    main()
