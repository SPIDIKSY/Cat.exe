"""Форматировщик CAT (`cat fmt`): единый вид кода, чтобы и люди, и ИИ писали одинаково.

Правила: отступ 4 пробела по глубине фигурных скобок, без пробелов в конце строк, табуляция -> пробелы,
не больше одной пустой строки подряд, один перевод строки в конце файла. Комментарии и строки не трогает.
Идемпотентен: повторный запуск ничего не меняет.
"""


def _braces(line):
    """(сколько { , сколько } , сколько } в самом начале строки) — вне строк и комментариев."""
    opens = closes = lead = 0
    in_str = False
    seen_code = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str, seen_code = True, True
        elif line.startswith("//", i):
            break
        elif c == "{":
            opens, seen_code = opens + 1, True
        elif c == "}":
            closes += 1
            if not seen_code:
                lead += 1
        elif not c.isspace():
            seen_code = True
        i += 1
    return opens, closes, lead


def format_source(text):
    out, depth, blank = [], 0, 0
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.replace("\t", "    ").strip()
        if not line:
            blank += 1
            continue
        opens, closes, lead = _braces(line)
        indent = max(depth - lead, 0)
        if blank and out:
            out.append("")
        blank = 0
        out.append("    " * indent + line)
        depth = max(depth + opens - closes, 0)
    return "\n".join(out) + "\n" if out else ""
