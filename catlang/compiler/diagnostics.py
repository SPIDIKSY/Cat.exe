"""Ошибки компиляции, их красивый вывод и стабильные коды (для людей и для ИИ)."""
import re

# (регулярное выражение по тексту сообщения, код, короткое имя). Коды не меняются между версиями.
CODES = [
    (r"unterminated string", "E0001", "unterminated-string"),
    (r"bad number literal", "E0002", "bad-number"),
    (r"unexpected character|unknown escape", "E0003", "bad-character"),
    (r"^expected |unexpected end of file|only a variable", "E0010", "syntax"),
    (r"type mismatch", "E0100", "type-mismatch"),
    (r"does not fit", "E0101", "literal-out-of-range"),
    (r"cannot be applied", "E0102", "bad-operator"),
    (r"cannot cast|cannot be cast", "E0103", "bad-cast"),
    (r"cannot infer", "E0104", "cannot-infer"),
    (r"cannot print|cannot store|cannot index|has no fields|immutable|needs an array|needs an integer|"
     r"array elements|range must be", "E0105", "bad-operand"),
    (r"undefined variable", "E0200", "undefined-variable"),
    (r"undefined function", "E0201", "undefined-function"),
    (r"unknown type", "E0202", "unknown-type"),
    (r"unknown module", "E0203", "unknown-module"),
    (r"no field", "E0204", "no-such-field"),
    (r"already declared|defined twice|already used|is a built-in", "E0210", "duplicate-name"),
    (r"without returning", "E0300", "missing-return"),
    (r"program has no|'main' must", "E0301", "bad-main"),
    (r"outside of a loop", "E0302", "loop-control-outside-loop"),
    (r"needs a value|returns nothing", "E0303", "bad-return"),
    (r"takes \d+ argument|field\(s\), got", "E0304", "wrong-argument-count"),
]


def classify(message):
    for pattern, code, name in CODES:
        if re.search(pattern, message):
            return code, name
    return "E0999", "error"


class CatError(Exception):
    def __init__(self, message, line=0, col=0, file=None):
        super().__init__(message)
        self.message, self.line, self.col, self.file = message, line, col, file

    @property
    def code(self):
        return classify(self.message)[0]

    def to_dict(self, sources=None):
        text = (sources or {}).get(self.file)
        lines = text.split("\n") if text else []
        return {"code": self.code, "name": classify(self.message)[1], "severity": "error",
                "file": self.file, "line": self.line, "column": self.col, "message": self.message,
                "source": lines[self.line - 1] if 1 <= self.line <= len(lines) else None}


class CompileError(Exception):
    """Набор ошибок компиляции + исходники для вывода."""

    def __init__(self, errors, sources):
        super().__init__(f"{len(errors)} error(s)")
        self.errors, self.sources = errors, sources

    def render(self):
        return "\n".join(render(e, self.sources) for e in self.errors)

    def to_json(self):
        import json
        return json.dumps({"ok": False, "errors": [e.to_dict(self.sources) for e in self.errors]},
                          ensure_ascii=False, indent=2)


def render(err, sources):
    head = f"{err.file or '<input>'}:{err.line}:{err.col}: error[{err.code}]: {err.message}"
    text = sources.get(err.file)
    if text and 1 <= err.line <= len(text.split("\n")):
        src = text.split("\n")[err.line - 1].replace("\t", " ")
        pad = " " * (max(err.col, 1) - 1)
        return f"{head}\n {err.line:>4} | {src}\n      | {pad}^"
    return head
