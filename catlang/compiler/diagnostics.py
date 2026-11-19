"""Ошибки компиляции и их красивый вывод."""


class CatError(Exception):
    def __init__(self, message, line=0, col=0, file=None):
        super().__init__(message)
        self.message, self.line, self.col, self.file = message, line, col, file


class CompileError(Exception):
    """Набор ошибок компиляции + исходники для вывода."""

    def __init__(self, errors, sources):
        super().__init__(f"{len(errors)} error(s)")
        self.errors, self.sources = errors, sources

    def render(self):
        return "\n".join(render(e, self.sources) for e in self.errors)


def render(err, sources):
    head = f"{err.file or '<input>'}:{err.line}:{err.col}: error: {err.message}"
    text = sources.get(err.file)
    if text and 1 <= err.line <= len(text.split("\n")):
        src = text.split("\n")[err.line - 1].replace("\t", " ")
        pad = " " * (max(err.col, 1) - 1)
        return f"{head}\n {err.line:>4} | {src}\n      | {pad}^"
    return head
