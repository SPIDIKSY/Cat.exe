"""Платформенный слой: ВСЁ взаимодействие с ОС (консоль, файлы) — только здесь.

Остальной код CAT (компилятор, VM) не обращается к sys/os напрямую.
"""
import os
import sys


def setup_console():
    """Вывод в UTF-8 (чтобы русский текст не ломался в консоли Windows)."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def write_out(text):
    sys.stdout.write(text)


def write_err(text):
    sys.stderr.write(text)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


def exists(path):
    return os.path.isfile(path)


def stdlib_path(module):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "stdlib", module + ".cat")
