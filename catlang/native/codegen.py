"""Нативный бэкенд x86-64: типизированное дерево CAT -> машинный код.

Простая и надёжная схема: каждое значение — каноническое 64-битное целое в rax (знаковые расширены знаком,
беззнаковые нулём), после операций оно приводится к своему типу. Временные значения — в стеке.
Локальные переменные — [rbp - 8*(слот+1)]. Вызов: аргументы кладутся в стек слева направо, результат в rax.
r15 — адрес пользовательской памяти (look*/bat*). Печать, ввод и random — это stdlib/rt.cat, написанный на CAT.
Пока без кучи: массивы, строки-значения и структуры не поддерживаются.
"""
import dataclasses

from ..compiler import ast as A
from ..compiler.diagnostics import CatError, CompileError
from ..core.cattypes import BOOL, STR, U32, VOID
from . import asm as X
from .platform import emit_stubs

USER_MEM, RT_MEM = 65536, 8192
BSS_SIZE = USER_MEM + RT_MEM
SEED_ADDR = USER_MEM  # состояние rng
CC_S = {"==": X.E, "!=": X.NE, "<": X.L, "<=": X.LE, ">": X.G, ">=": X.GE}
CC_U = {"==": X.E, "!=": X.NE, "<": X.B, "<=": X.BE, ">": X.A, ">=": X.AE}


class Unsupported(Exception):
    def __init__(self, node, what):
        super().__init__(what)
        self.node, self.what = node, what


def walk(node):
    if isinstance(node, list):
        for x in node:
            yield from walk(x)
    elif dataclasses.is_dataclass(node) and not isinstance(node, type):
        yield node
        for f in dataclasses.fields(node):
            v = getattr(node, f.name)
            if isinstance(v, (list, A.Node)):
                yield from walk(v)


def default_rng_seed(seed):
    """Начальное состояние генератора — то же правило, что в виртуальной машине."""
    return ((seed or 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF) or 1


class NativeGen:
    def __init__(self, funcs, target, seed=None):
        self.funcs = {f.name: f for f in funcs}
        self.target, self.seed = target, seed
        self.a = X.Asm()
        self.order, self.lits, self.uid, self.cur = [], {}, 0, None

    # --- какие функции нужны ---
    def rt_for(self, call):
        n = call.target
        if n in ("meow", "mew"):
            a = call.args[0]
            if isinstance(a, A.StrLit):
                return "rt.print_str"
            if a.ty is BOOL:
                return "rt.print_bool"
            if a.ty.ref:
                raise Unsupported(a, "strings as values")
            return "rt.print_u64" if a.ty.bits == 64 and not a.ty.signed else "rt.print_i64"
        return {"roll": "rt.do_roll", "ask": "rt.do_ask", "heard": "rt.do_heard"}.get(n)

    def reach(self):
        todo, seen = ["main"], set()
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            self.order.append(n)
            for node in walk(self.funcs[n].body):
                if isinstance(node, A.Call) and node.struct is None:
                    t = self.rt_for(node) if node.builtin else node.target
                    if t:
                        todo.append(t)
                if isinstance(node, A.Call) and node.builtin and node.target == "ask":
                    todo.append("rt.do_ask")

    # --- помощники ---
    def newlabel(self, kind="L"):
        self.uid += 1
        return f".{kind}{self.uid}"

    def lit(self, s):
        if s not in self.lits:
            self.lits[s] = f".lit{len(self.lits)}"
        return self.lits[s]

    def norm(self, t):
        a = self.a
        if t is BOOL:
            a.raw(0x83, 0xE0, 0x01)  # and eax, 1
        elif t.bits in (8, 16, 32):
            a.extend(t.bits, t.signed)

    def slot(self, i):
        return -8 * (i + 1)

    # --- построение ---
    def build(self):
        a = self.a
        self.reach()
        # точка входа
        a.label("_start")
        a.lea_extern(X.R15, "bss")
        if self.seed is not None:
            a.mov_ri(X.RAX, default_rng_seed(self.seed))
        else:
            a.rdtsc()
            a.shl_imm(X.RDX, 32)
            a.alu_rr("or", X.RAX, X.RDX)
            a.test_eax_rax()
            a.jcc(X.NE, ".seedok")
            a.mov_ri(X.RAX, 1)
            a.label(".seedok")
        a.store_r15(SEED_ADDR, X.RAX)
        if self.target == "windows":  # консоль в UTF-8, чтобы русский текст не ломался
            a.alu_ri("sub", X.RSP, 40)
            a.mov_ri(X.RCX, 65001)
            a.call_extern("iat:SetConsoleOutputCP")
            a.mov_ri(X.RCX, 65001)
            a.call_extern("iat:SetConsoleCP")
            a.alu_ri("add", X.RSP, 40)
        a.call("f:main")
        a.mov_rr(X.RDI, X.RAX)
        a.alu_ri("and", X.RDI, 0xFF)
        a.call("os_exit")
        emit_stubs(a, self.target)
        for k, name in ((1, "trap_div"), (2, "trap_shift"), (3, "trap_assert"), (4, "trap_mem")):
            a.label(name)
            a.mov_ri(X.RDI, k)
            a.call("os_trap")
        for n in self.order:
            self.function(self.funcs[n])
        for s, name in self.lits.items():
            a.label(name)
            a.data(s.encode("utf-8"))
        a.resolve()
        return a

    def function(self, f):
        a = self.a
        for t in f.param_types + [f.ret_type]:
            if t.ref:
                raise Unsupported(f, "arrays, strings and structures")
        self.cur = f
        self.ret = self.newlabel("ret")
        self.loops = []
        a.label(f"f:{f.name}")
        a.push(X.RBP)
        a.mov_rr(X.RBP, X.RSP)
        if f.nlocals:
            a.alu_ri("sub", X.RSP, 8 * f.nlocals)
        n = len(f.params)
        for i in range(n):
            a.load_rbp(X.RAX, 16 + 8 * (n - 1 - i))
            a.store_rbp(self.slot(i), X.RAX)
        self.block(f.body)
        a.mov_ri(X.RAX, 0)
        a.label(self.ret)
        a.leave()
        a.ret()

    # --- операторы ---
    def block(self, b):
        for s in b.stmts:
            self.stmt(s)

    def stmt(self, s):
        a = self.a
        if isinstance(s, (A.Let, A.Assign)):
            self.expr(s.init if isinstance(s, A.Let) else s.value)
            a.store_rbp(self.slot(s.slot), X.RAX)
        elif isinstance(s, A.If):
            els, end = self.newlabel(), self.newlabel()
            self.expr(s.cond)
            a.test_eax()
            a.jcc(X.E, els)
            self.block(s.then)
            if s.other:
                a.jmp(end)
            a.label(els)
            if s.other:
                self.stmt(s.other)
                a.label(end)
        elif isinstance(s, A.While):
            top, end = self.newlabel(), self.newlabel()
            a.label(top)
            self.expr(s.cond)
            a.test_eax()
            a.jcc(X.E, end)
            self.loops.append((top, end))
            self.block(s.body)
            self.loops.pop()
            a.jmp(top)
            a.label(end)
        elif isinstance(s, A.For):
            top, cont, end = self.newlabel(), self.newlabel(), self.newlabel()
            self.expr(s.start)
            a.store_rbp(self.slot(s.slot), X.RAX)
            self.expr(s.end)
            a.store_rbp(self.slot(s.endslot), X.RAX)
            a.label(top)
            a.load_rbp(X.RAX, self.slot(s.slot))
            a.load_rbp(X.RCX, self.slot(s.endslot))
            a.alu_rr("cmp", X.RAX, X.RCX)
            a.jcc(X.AE if (s.ty.bits == 64 and not s.ty.signed) else X.GE, end)
            self.loops.append((cont, end))
            self.block(s.body)
            self.loops.pop()
            a.label(cont)
            a.load_rbp(X.RAX, self.slot(s.slot))
            a.alu_ri("add", X.RAX, 1)
            self.norm(s.ty)
            a.store_rbp(self.slot(s.slot), X.RAX)
            a.jmp(top)
            a.label(end)
        elif isinstance(s, A.Break):
            a.jmp(self.loops[-1][1])
        elif isinstance(s, A.Continue):
            a.jmp(self.loops[-1][0])
        elif isinstance(s, A.Return):
            if s.value is not None:
                self.expr(s.value)
            else:
                a.mov_ri(X.RAX, 0)
            a.jmp(self.ret)
        elif isinstance(s, A.Block):
            self.block(s)
        elif isinstance(s, A.ExprStmt):
            self.expr(s.expr)
        else:
            raise Unsupported(s, "arrays and structures")

    # --- выражения (результат в rax) ---
    def expr(self, e):
        a = self.a
        if isinstance(e, (A.IntLit, A.BoolLit)):
            a.mov_ri(X.RAX, int(e.value))
        elif isinstance(e, A.Var):
            a.load_rbp(X.RAX, self.slot(e.slot))
        elif isinstance(e, A.Unary):
            self.expr(e.operand)
            t = e.ty
            if e.op == "meow" and t is BOOL:
                a.xor_eax_imm1()
            elif e.op == "meow":
                a.unary("not", X.RAX)
                self.norm(t)
            else:
                a.unary("neg", X.RAX)
                self.norm(t)
        elif isinstance(e, A.Cast):
            self.expr(e.operand)
            self.norm(e.ty)
        elif isinstance(e, A.Binary):
            self.binary(e)
        elif isinstance(e, A.Call):
            self.call(e)
        else:
            raise Unsupported(e, "arrays, strings and structures")

    def binary(self, e):
        a, op = self.a, e.op
        if op in ("&&", "||"):
            end = self.newlabel()
            self.expr(e.left)
            a.test_eax()
            a.jcc(X.E if op == "&&" else X.NE, end)
            self.expr(e.right)
            a.label(end)  # при коротком замыкании в rax уже лежит 0 (&&) или 1 (||)
            return
        if e.left.ty.ref:
            raise Unsupported(e, "arrays, strings and structures")
        self.expr(e.left)
        a.push(X.RAX)
        self.expr(e.right)
        a.mov_rr(X.RCX, X.RAX)
        a.pop(X.RAX)
        t = e.left.ty
        if op in CC_S:
            a.alu_rr("cmp", X.RAX, X.RCX)
            a.setcc((CC_U if t.bits == 64 and not t.signed else CC_S)[op])
        elif op in ("+", "-", "*"):
            {"+": lambda: a.alu_rr("add", X.RAX, X.RCX), "-": lambda: a.alu_rr("sub", X.RAX, X.RCX),
             "*": lambda: a.imul_rr(X.RAX, X.RCX)}[op]()
            self.norm(t)
        elif op in ("cat", "cats", "paw"):
            a.alu_rr({"cat": "and", "cats": "or", "paw": "xor"}[op], X.RAX, X.RCX)
        elif op in ("/", "%"):
            a.alu_rr("test", X.RCX, X.RCX)
            a.jcc(X.E, "trap_div")
            if t.signed:
                ok, done = self.newlabel(), self.newlabel()
                a.alu_ri("cmp", X.RCX, -1)
                a.jcc(X.NE, ok)
                if op == "/":
                    a.unary("neg", X.RAX)      # INT_MIN / -1 оборачивается, а не падает
                else:
                    a.mov_ri(X.RAX, 0)
                a.jmp(done)
                a.label(ok)
                a.cqo()
                a.unary("idiv", X.RCX)
                if op == "%":
                    a.mov_rr(X.RAX, X.RDX)
                a.label(done)
            else:
                a.mov_ri(X.RDX, 0)
                a.unary("div", X.RCX)
                if op == "%":
                    a.mov_rr(X.RAX, X.RDX)
            self.norm(t)
        elif op in ("<<", ">>"):
            a.alu_ri("cmp", X.RCX, t.bits)
            a.jcc(X.AE, "trap_shift")
            a.shift_cl("shl" if op == "<<" else ("sar" if t.signed else "shr"), X.RAX)
            if op == "<<":
                self.norm(t)
        else:
            raise AssertionError(op)

    def push_args(self, args):
        for x in args:
            self.expr(x)
            self.a.push(X.RAX)

    def call(self, e):
        a = self.a
        if e.struct is not None:
            raise Unsupported(e, "structures")
        if not e.builtin:
            self.push_args(e.args)
            a.call(f"f:{e.target}")
            if e.args:
                a.alu_ri("add", X.RSP, 8 * len(e.args))
            return
        n = e.target
        if n in ("meow", "mew"):
            nl = 1 if n == "meow" else 0
            arg = e.args[0]
            fn = self.rt_for(e)
            if isinstance(arg, A.StrLit):
                b = arg.value.encode("utf-8")
                a.lea_label(X.RAX, self.lit(arg.value))
                a.push(X.RAX)
                a.mov_ri(X.RAX, len(b))
                a.push(X.RAX)
                k = 3
            else:
                self.expr(arg)
                a.push(X.RAX)
                k = 2
            a.mov_ri(X.RAX, nl)
            a.push(X.RAX)
            a.call(f"f:{fn}")
            a.alu_ri("add", X.RSP, 8 * k)
        elif n == "claw":
            ok = self.newlabel()
            self.expr(e.args[0])
            a.test_eax()
            a.jcc(X.NE, ok)
            a.jmp("trap_assert")
            a.label(ok)
        elif n in ("roll", "ask", "heard"):
            fn = {"roll": "rt.do_roll", "ask": "rt.do_ask", "heard": "rt.do_heard"}[n]
            self.push_args(e.args)
            a.call(f"f:{fn}")
            if e.args:
                a.alu_ri("add", X.RSP, 8)
        elif n.startswith("look"):
            bits = int(n[4:])
            self.expr(e.args[0])
            self.check_mem(bits // 8)
            a.load_mem(bits)
        elif n.startswith("bat"):
            bits = int(n[3:])
            self.expr(e.args[0])
            a.push(X.RAX)
            self.expr(e.args[1])
            a.mov_rr(X.RCX, X.RAX)
            a.pop(X.RAX)
            self.check_mem(bits // 8)
            a.store_mem(bits)
        elif n in ("__write", "__read"):
            self.push_args(e.args)
            a.pop(X.RDX)
            a.pop(X.RSI)
            a.pop(X.RDI)
            a.call("os_write" if n == "__write" else "os_read")
        elif n == "__exit":
            self.expr(e.args[0])
            a.mov_rr(X.RDI, X.RAX)
            a.call("os_exit")
        elif n == "__trap":
            self.expr(e.args[0])
            a.mov_rr(X.RDI, X.RAX)
            a.call("os_trap")
        elif n == "__mem":
            a.mov_rr(X.RAX, X.R15)
        elif n == "__rdtsc":
            a.rdtsc()
            a.shl_imm(X.RDX, 32)
            a.alu_rr("or", X.RAX, X.RDX)
        else:
            raise Unsupported(e, f"the built-in '{n}'")

    def check_mem(self, nbytes):
        """Адрес в rax должен помещаться в пользовательскую память (для рантайма — шире)."""
        limit = USER_MEM + (RT_MEM if self.cur.module == "rt" else 0)
        self.a.alu_ri("cmp", X.RAX, limit - nbytes)
        self.a.jcc(X.A, "trap_mem")


def generate_native(funcs, target, seed=None):
    """Возвращает Asm: код (a.buf), метки, внешние ссылки. При неподдерживаемом бросает CompileError."""
    gen = NativeGen(funcs, target, seed)
    try:
        return gen.build(), gen
    except Unsupported as u:
        node = u.node
        raise CompileError([CatError(f"the native backend does not support {u.what} yet",
                                     getattr(node, "line", 0), getattr(node, "col", 0),
                                     getattr(node, "file", None) or getattr(gen.cur, "file", None))], {})
