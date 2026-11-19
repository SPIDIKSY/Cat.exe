"""Лексер CAT: текст -> список токенов."""
from collections import namedtuple

from .diagnostics import CatError

Token = namedtuple("Token", "kind value line col")  # kind: int str id kw op eof

KEYWORDS = {"fn", "let", "if", "else", "while", "return", "as", "true", "false",
            "use", "cat", "cats", "meow", "paw"}
OPS3 = ()
OPS2 = {"==", "!=", "<=", ">=", "<<", ">>", "->"}
OPS1 = set("(){},;:=<>+-*/%.")
ESC = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "0": "\0"}


def tokenize(src, file=None):
    toks, i, line, col, n = [], 0, 1, 1, len(src)

    def err(msg, l=None, c=None):
        raise CatError(msg, l or line, c or col, file)

    while i < n:
        ch = src[i]
        if ch == "\n":
            i, line, col = i + 1, line + 1, 1
        elif ch in " \t\r":
            i, col = i + 1, col + 1
        elif src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            toks.append(Token("kw" if w in KEYWORDS else "id", w, line, col))
            col += j - i
            i = j
        elif ch.isdigit():
            j = i
            if src.startswith(("0x", "0X"), i):
                j += 2
                while j < n and (src[j] in "0123456789abcdefABCDEF_"):
                    j += 1
                base = 16
            elif src.startswith(("0b", "0B"), i):
                j += 2
                while j < n and src[j] in "01_":
                    j += 1
                base = 2
            else:
                while j < n and (src[j].isdigit() or src[j] == "_"):
                    j += 1
                base = 10
            text = src[i:j].replace("_", "")
            try:
                val = int(text, base)
            except ValueError:
                err(f"bad number literal '{src[i:j]}'")
            if j < n and (src[j].isalpha()):
                err(f"bad number literal '{src[i:j + 1]}'")
            toks.append(Token("int", val, line, col))
            col += j - i
            i = j
        elif ch == '"':
            sl, sc = line, col
            j, out = i + 1, []
            while True:
                if j >= n or src[j] == "\n":
                    err("unterminated string", sl, sc)
                c = src[j]
                if c == '"':
                    break
                if c == "\\":
                    j += 1
                    if j >= n or src[j] not in ESC:
                        err("unknown escape in string", line, col + (j - i))
                    c = ESC[src[j]]
                out.append(c)
                j += 1
            toks.append(Token("str", "".join(out), sl, sc))
            col += j + 1 - i
            i = j + 1
        elif src[i:i + 2] in OPS2:
            toks.append(Token("op", src[i:i + 2], line, col))
            i, col = i + 2, col + 2
        elif ch in OPS1:
            toks.append(Token("op", ch, line, col))
            i, col = i + 1, col + 1
        else:
            err(f"unexpected character {ch!r}")
    toks.append(Token("eof", None, line, col))
    return toks
