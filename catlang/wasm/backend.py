"""Бэкенд WebAssembly: типизированное дерево CAT -> .wasm (свой кодировщик).

Значения: bool, u8..u32, i8..i32 — i32 (малые типы после каждой операции приводятся к своему диапазону);
u64, i64 — i64. Знаковость выбирает вариант команды (lt_s/lt_u, div_s/div_u ...).
Семантика совпадает с VM: целые оборачиваются, деление на 0 и сдвиг за пределы типа — ловушка,
INT_MIN / -1 оборачивается (для этого есть вспомогательная функция div).
Не поддерживается пока: массивы, строки-значения, структуры, ghost, bury, look*/bat* (нужна куча в Wasm).
"""
import dataclasses

from ..compiler import ast as A
from ..compiler.diagnostics import CatError, CompileError
from ..core.cattypes import BOOL, I64 as I64T, VOID, wrap
from .encode import I32, I64, Module, sleb, uleb

IMPORTS = [
    ("print_i64", [I64], []), ("write_i64", [I64], []), ("print_u64", [I64], []), ("write_u64", [I64], []),
    ("print_bool", [I32], []), ("write_bool", [I32], []),
    ("print_str", [I32, I32], []), ("write_str", [I32, I32], []),
    ("roll", [I32], [I32]), ("ask", [], [I64]), ("heard", [], [I32]),
]
IMP = {n: i for i, (n, _, _) in enumerate(IMPORTS)}
HELPERS = ["div32", "div64", "shl32", "shr_s32", "shr_u32", "shl64", "shr_s64", "shr_u64"]
HELP = {n: len(IMPORTS) + i for i, n in enumerate(HELPERS)}
DATA_START = 1024

# коды команд
OP32 = {"eqz": 0x45, "eq": 0x46, "ne": 0x47, "lt_s": 0x48, "lt_u": 0x49, "gt_s": 0x4A, "gt_u": 0x4B,
        "le_s": 0x4C, "le_u": 0x4D, "ge_s": 0x4E, "ge_u": 0x4F, "add": 0x6A, "sub": 0x6B, "mul": 0x6C,
        "div_s": 0x6D, "div_u": 0x6E, "rem_s": 0x6F, "rem_u": 0x70, "and": 0x71, "or": 0x72, "xor": 0x73}
OP64 = {"eqz": 0x50, "eq": 0x51, "ne": 0x52, "lt_s": 0x53, "lt_u": 0x54, "gt_s": 0x55, "gt_u": 0x56,
        "le_s": 0x57, "le_u": 0x58, "ge_s": 0x59, "ge_u": 0x5A, "add": 0x7C, "sub": 0x7D, "mul": 0x7E,
        "div_s": 0x7F, "div_u": 0x80, "rem_s": 0x81, "rem_u": 0x82, "and": 0x83, "or": 0x84, "xor": 0x85}
CMP = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
ARITH = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "rem", "cat": "and", "cats": "or", "paw": "xor"}


class Unsupported(Exception):
    def __init__(self, node, what):
        super().__init__(what)
        self.node, self.what = node, what


def wide(t):
    return t.bits == 64


def valtype(t, node=None):
    if t.ref or t.bits == 0:
        raise Unsupported(node, f"values of type '{t}'")
    return I64 if wide(t) else I32


def walk(node):
    """Все узлы дерева (для поиска вызовов и типов переменных)."""
    if isinstance(node, list):
        for x in node:
            yield from walk(x)
    elif dataclasses.is_dataclass(node) and not isinstance(node, type):
        yield node
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if isinstance(v, (list, A.Node)):
                yield from walk(v)


def _helpers(m):
    """Вспомогательные функции модуля (индексы совпадают с HELPERS)."""
    def g(i):
        return b"\x20" + uleb(i)

    # div32/div64: a / b, но INT_MIN / -1 оборачивается вместо ловушки
    for t, c, neg_one in ((I32, 0x41, b"\x41\x7f"), (I64, 0x42, b"\x42\x7f")):
        o = OP32 if t == I32 else OP64
        zero = bytes([c, 0])
        body = (g(1) + neg_one + bytes([o["eq"]]) + b"\x04" + bytes([t]) + zero + g(0) + bytes([o["sub"]])
                + b"\x05" + g(0) + g(1) + bytes([o["div_s"]]) + b"\x0b")
        m.add_func([t, t], [t], [], body)
    # сдвиги: amount >= предела -> ловушка
    for t, shl, shr_s, shr_u, ge_u in ((I32, 0x74, 0x75, 0x76, 0x4F), (I64, 0x86, 0x87, 0x88, 0x5A)):
        params = [t, t, I32] if t == I32 else [t, t]
        limit = g(2) if t == I32 else b"\x42" + sleb(64)
        for opc in (shl, shr_s, shr_u):
            body = g(1) + limit + bytes([ge_u]) + b"\x04\x40\x00\x0b" + g(0) + g(1) + bytes([opc])
            m.add_func(params, [t], [], body)


class FuncGen:
    def __init__(self, gen, f):
        self.gen, self.f, self.out, self.ctl, self.uid = gen, f, bytearray(), [], 0

    # --- низкий уровень ---
    def b(self, *bs):
        self.out += bytes(bs)

    def const(self, t, v):
        if wide(t):
            self.out += b"\x42" + sleb(wrap(v, I64T))
        else:
            v &= 0xFFFFFFFF
            self.out += b"\x41" + sleb(v - (1 << 32) if v >> 31 else v)

    def op(self, t, name):
        self.b((OP64 if wide(t) else OP32)[name])

    def norm(self, t):
        if t is BOOL:
            self.b(0x41, 1, 0x71)
        elif t.bits in (8, 16) and not t.signed:
            self.out += b"\x41" + sleb(t.mask) + b"\x71"
        elif t.bits == 8 and t.signed:
            self.b(0xC0)
        elif t.bits == 16 and t.signed:
            self.b(0xC1)

    def call(self, idx):
        self.out += b"\x10" + uleb(idx)

    def local(self, kind, slot):
        self.out += bytes([kind]) + uleb(slot)

    # --- метки управления ---
    def depth(self, kind):
        for i in range(len(self.ctl) - 1, -1, -1):
            if self.ctl[i] == kind:
                return len(self.ctl) - 1 - i
        raise AssertionError(kind)

    # --- операторы ---
    def block(self, blk):
        for s in blk.stmts:
            self.stmt(s)

    def stmt(self, s):
        if isinstance(s, A.Let):
            self.expr(s.init)
            self.local(0x21, s.slot)
        elif isinstance(s, A.Assign):
            self.expr(s.value)
            self.local(0x21, s.slot)
        elif isinstance(s, A.If):
            self.expr(s.cond)
            self.b(0x04, 0x40)
            self.ctl.append("if")
            self.block(s.then)
            if s.other:
                self.b(0x05)
                self.stmt(s.other)
            self.ctl.pop()
            self.b(0x0B)
        elif isinstance(s, A.While):
            self.uid += 1
            brk, top = ("brk", self.uid), ("top", self.uid)
            self.b(0x02, 0x40, 0x03, 0x40)
            self.ctl += [brk, top]
            self.expr(s.cond)
            self.b(0x45, 0x0D)
            self.out += uleb(self.depth(brk))
            self.block(s.body)
            self.b(0x0C)
            self.out += uleb(self.depth(top))
            self.ctl[-2:] = []
            self.b(0x0B, 0x0B)
        elif isinstance(s, A.For):
            self.uid += 1
            brk, top, cont = ("brk", self.uid), ("top", self.uid), ("cont", self.uid)
            self.expr(s.start)
            self.local(0x21, s.slot)
            self.expr(s.end)
            self.local(0x21, s.endslot)
            self.b(0x02, 0x40, 0x03, 0x40)
            self.ctl += [brk, top]
            self.local(0x20, s.slot)
            self.local(0x20, s.endslot)
            self.op(s.ty, "lt_s" if s.ty.signed else "lt_u")
            self.b(0x45, 0x0D)
            self.out += uleb(self.depth(brk))
            self.b(0x02, 0x40)
            self.ctl.append(cont)
            self.block(s.body)
            self.ctl.pop()
            self.b(0x0B)
            self.local(0x20, s.slot)
            self.const(s.ty, 1)
            self.op(s.ty, "add")
            self.norm(s.ty)
            self.local(0x21, s.slot)
            self.b(0x0C)
            self.out += uleb(self.depth(top))
            self.ctl[-2:] = []
            self.b(0x0B, 0x0B)
        elif isinstance(s, A.Break):
            self.b(0x0C)
            self.out += uleb(self.depth(next(c for c in reversed(self.ctl) if c != "if" and c[0] == "brk")))
        elif isinstance(s, A.Continue):
            tgt = next(c for c in reversed(self.ctl) if c != "if" and c[0] in ("top", "cont"))
            self.b(0x0C)
            self.out += uleb(self.depth(tgt))
        elif isinstance(s, A.Return):
            if s.value is not None:
                self.expr(s.value)
            self.b(0x0F)
        elif isinstance(s, A.Block):
            self.block(s)
        elif isinstance(s, A.ExprStmt):
            self.expr(s.expr)
            if s.expr.ty is not VOID:
                self.b(0x1A)
        else:
            raise Unsupported(s, "array or structure element assignment")

    # --- выражения ---
    def expr(self, e):
        if isinstance(e, (A.IntLit, A.BoolLit)):
            self.const(e.ty, int(e.value))
        elif isinstance(e, A.Var):
            self.local(0x20, e.slot)
        elif isinstance(e, A.Unary):
            t = e.ty
            if e.op == "meow" and t is BOOL:
                self.expr(e.operand)
                self.b(0x45)
            elif e.op == "meow":
                self.expr(e.operand)
                self.const(t, -1)
                self.op(t, "xor")
                self.norm(t)
            else:
                self.const(t, 0)
                self.expr(e.operand)
                self.op(t, "sub")
                self.norm(t)
        elif isinstance(e, A.Cast):
            self.cast(e)
        elif isinstance(e, A.Binary):
            self.binary(e)
        elif isinstance(e, A.Call):
            self.call_expr(e)
        else:
            raise Unsupported(e, {"StrLit": "strings as values", "Nil": "'ghost'", "Field": "structures",
                                  "Index": "arrays", "ArrayLit": "arrays", "ArrayRepeat": "arrays"}[type(e).__name__])

    def cast(self, e):
        src, dst = e.operand.ty, e.ty
        self.expr(e.operand)
        if not wide(src) and wide(dst):
            self.b(0xAC if src.signed else 0xAD)
        elif wide(src) and not wide(dst):
            self.b(0xA7)
            self.norm(dst)
        elif not wide(src):
            self.norm(dst)

    def binary(self, e):
        op = e.op
        if op in ("&&", "||"):
            self.expr(e.left)
            self.b(0x04, I32)
            self.ctl.append("if")
            if op == "&&":
                self.expr(e.right)
                self.b(0x05, 0x41, 0)
            else:
                self.b(0x41, 1, 0x05)
                self.expr(e.right)
            self.ctl.pop()
            self.b(0x0B)
            return
        self.expr(e.left)
        self.expr(e.right)
        t = e.left.ty
        if op in CMP:
            name = CMP[op]
            self.op(t, name if name in ("eq", "ne") else f"{name}_{'s' if t.signed else 'u'}")
        elif op in ("<<", ">>"):
            w = wide(t)
            if op == "<<":
                h = "shl64" if w else "shl32"
            else:
                h = ("shr_s" if t.signed else "shr_u") + ("64" if w else "32")
            if not w:
                self.b(0x41, t.bits)
            self.call(HELP[h])
            if op == "<<":
                self.norm(t)
        elif op == "/" and t.signed and t.bits >= 32:
            self.call(HELP["div64" if wide(t) else "div32"])
        elif op in ("/", "%"):
            self.op(t, ("div" if op == "/" else "rem") + ("_s" if t.signed else "_u"))
            self.norm(t)
        else:
            self.op(t, ARITH[op])
            if op in ("+", "-", "*"):
                self.norm(t)

    def call_expr(self, e):
        if e.struct is not None:
            raise Unsupported(e, "structures")
        if not e.builtin:
            for a in e.args:
                self.expr(a)
            self.call(self.gen.fidx[e.target])
            return
        n = e.target
        if n in ("meow", "mew"):
            pre = "print" if n == "meow" else "write"
            a = e.args[0]
            if isinstance(a, A.StrLit):
                ptr, ln = self.gen.string(a.value)
                self.out += b"\x41" + sleb(ptr) + b"\x41" + sleb(ln)
                self.call(IMP[pre + "_str"])
            elif a.ty is BOOL:
                self.expr(a)
                self.call(IMP[pre + "_bool"])
            elif a.ty.ref:
                raise Unsupported(a, "printing strings that are values")
            else:
                self.expr(a)
                if not wide(a.ty):
                    self.b(0xAC if a.ty.signed else 0xAD)
                self.call(IMP[pre + ("_u64" if wide(a.ty) and not a.ty.signed else "_i64")])
        elif n == "claw":
            self.expr(e.args[0])
            self.b(0x45, 0x04, 0x40, 0x00, 0x0B)
        elif n == "roll":
            self.expr(e.args[0])
            self.call(IMP["roll"])
        elif n == "ask":
            self.call(IMP["ask"])
        elif n == "heard":
            self.call(IMP["heard"])
        else:
            raise Unsupported(e, f"the built-in '{n}'")


class Gen:
    def __init__(self, funcs):
        self.funcs = {f.name: f for f in funcs}
        self.order, self.fidx = [], {}
        self.data, self.next_data, self.str_cache = [], DATA_START, {}

    def string(self, s):
        if s not in self.str_cache:
            b = s.encode("utf-8")
            self.data.append((self.next_data, b))
            self.str_cache[s] = (self.next_data, len(b))
            self.next_data += len(b)
        return self.str_cache[s]

    def reach(self):
        todo = ["main"]
        while todo:
            n = todo.pop()
            if n in self.fidx:
                continue
            self.fidx[n] = len(IMPORTS) + len(HELPERS) + len(self.order)
            self.order.append(n)
            for node in walk(self.funcs[n].body):
                if isinstance(node, A.Call) and not node.builtin and node.struct is None:
                    todo.append(node.target)

    def build(self):
        self.reach()
        m = Module()
        for name, ps, rs in IMPORTS:
            m.add_import("env", name, ps, rs)
        _helpers(m)
        for n in self.order:
            f = self.funcs[n]
            try:
                params = [valtype(t, f) for t in f.param_types]
                results = [] if f.ret_type is VOID else [valtype(f.ret_type, f)]
                types = {}
                for node in walk(f.body):
                    if isinstance(node, A.Let):
                        types[node.slot] = valtype(node.init.ty, node)
                    elif isinstance(node, A.For):
                        types[node.slot] = types[node.endslot] = valtype(node.ty, node)
                locals_ = [types.get(i, I32) for i in range(len(params), f.nlocals)]
                g = FuncGen(self, f)
                g.block(f.body)
                if results:
                    g.b(0x00)  # конец недостижим: все пути возвращают значение
            except Unsupported as u:
                node = u.node or f
                raise CompileError([CatError(f"the WebAssembly backend does not support {u.what} yet",
                                             node.line, node.col, f.file)], {})
            m.add_func(params, results, locals_, bytes(g.out))
        main = self.funcs["main"]
        m.exports.append(("main", 0, self.fidx["main"]))
        m.exports.append(("memory", 2, 0))
        m.data = self.data
        return m.to_bytes(), main.ret_type is not VOID


def compile_wasm(funcs):
    """funcs — функции после проверки типов и оптимизации. Возвращает (байты .wasm, main_возвращает_i32)."""
    return Gen(funcs).build()
