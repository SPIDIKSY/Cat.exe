"""Переводчик «старых» английских слов в кошачьи. Нужен только тестам, написанным
до смены словаря: строки и комментарии не трогает."""
import re

KW = {"fn": "purr", "let": "yarn", "if": "sniff", "else": "hiss", "while": "chase", "for": "prowl",
      "in": "among", "break": "scat", "continue": "hop", "return": "bring", "as": "like",
      "true": "yes", "false": "no", "use": "adopt", "cat": "C", "cats": "A", "meow": "T", "paw": "S"}
BI = {"print": "meow", "write": "mew", "assert": "claw", "read_int": "ask", "input_ok": "heard", "rand": "roll"}
for n in (8, 16, 32, 64):
    BI[f"peek{n}"], BI[f"poke{n}"] = f"look{n}", f"bat{n}"
MAP = {**KW, **BI}
RX = re.compile(r'("(?:\\.|[^"\\\n])*")|(//[^\n]*)|([A-Za-z_][A-Za-z_0-9]*)')


def convert(src):
    return RX.sub(lambda m: m.group(0) if m.group(3) is None else MAP.get(m.group(3), m.group(3)), src)
