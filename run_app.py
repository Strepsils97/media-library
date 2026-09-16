"""Точка входу для зібраного застосунку."""

import multiprocessing
import sys

if __name__ == "__main__":
    # PyInstaller + multiprocessing на Windows без цього породжує нові копії
    # вікна замість робочих процесів.
    multiprocessing.freeze_support()

    from backend.app.main import main

    sys.exit(main())
