"""Запись бинарного формата WebAssembly (.wasm) — полностью своя, без внешних библиотек."""

I32, I64 = 0x7F, 0x7E


def uleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def vec(items):
    return uleb(len(items)) + b"".join(items)


def name(s):
    b = s.encode("utf-8")
    return uleb(len(b)) + b


def section(sid, body):
    return bytes([sid]) + uleb(len(body)) + body


class Module:
    """Сборка модуля: типы, импорты, функции, память, экспорты, данные."""

    def __init__(self, pages=1):
        self.types, self.imports, self.funcs, self.exports, self.data = [], [], [], [], []
        self.pages = pages  # размер памяти в страницах по 64 КиБ

    def type_index(self, params, results):
        t = (tuple(params), tuple(results))
        if t not in self.types:
            self.types.append(t)
        return self.types.index(t)

    def add_import(self, module, field, params, results):
        self.imports.append((module, field, self.type_index(params, results)))
        return len(self.imports) - 1

    def add_func(self, params, results, local_types, body):
        """Возвращает индекс функции (после всех импортов). body — байты инструкций без завершающего end."""
        self.funcs.append((self.type_index(params, results), local_types, body))

    def func_index(self, i):
        return len(self.imports) + i

    def to_bytes(self):
        out = b"\0asm" + (1).to_bytes(4, "little")
        out += section(1, vec([b"\x60" + vec([bytes([p]) for p in ps]) + vec([bytes([r]) for r in rs])
                               for ps, rs in self.types]))
        out += section(2, vec([name(m) + name(f) + b"\x00" + uleb(t) for m, f, t in self.imports]))
        out += section(3, vec([uleb(t) for t, _, _ in self.funcs]))
        out += section(5, vec([b"\x00" + uleb(self.pages)]))
        out += section(7, vec([name(n) + bytes([kind]) + uleb(i) for n, kind, i in self.exports]))
        bodies = []
        for _, locals_, body in self.funcs:
            groups = []  # подряд идущие локальные одного типа
            for t in locals_:
                if groups and groups[-1][1] == t:
                    groups[-1][0] += 1
                else:
                    groups.append([1, t])
            code = vec([uleb(n) + bytes([t]) for n, t in groups]) + body + b"\x0b"
            bodies.append(uleb(len(code)) + code)
        out += section(10, vec(bodies))
        if self.data:
            out += section(11, vec([b"\x00\x41" + sleb(off) + b"\x0b" + uleb(len(b)) + b for off, b in self.data]))
        return out
