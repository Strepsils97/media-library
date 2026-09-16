"""Точка входу для зібраного застосунку."""

import multiprocessing
import sys
from pathlib import Path

if __name__ == "__main__":
    # PyInstaller + multiprocessing на Windows без цього породжує нові копії
    # вікна замість робочих процесів.
    multiprocessing.freeze_support()

    # Наш код їде поруч із екзешником звичайними файлами, а не в архіві
    # всередині нього, — щоб виправлення бекенда розкочувалося копіюванням.
    # Тека розпакування вже є в sys.path, але лише в кінці: ставимо на початок,
    # щоб випадковий однойменний пакет із залежностей не переважив наш.
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled and bundled not in sys.path[:1]:
        sys.path.insert(0, str(Path(bundled)))

    from backend.app.main import main

    sys.exit(main())
