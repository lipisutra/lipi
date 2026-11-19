#!/usr/bin/env python3
"""Запуск чекера lipi из исходников или установленного пакета.

    python3 src/lipi/check.py [--root проект] [--audit] [--format json]

Реализация проверок находится в пакете lipi.checker.
"""
import sys
from pathlib import Path

# На Windows stdout по умолчанию в кодировке консоли (cp1252), и русские
# сообщения роняли бы печать. Чекер всегда печатает в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lipi.checker.runner import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
