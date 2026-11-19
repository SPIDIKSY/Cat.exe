"""Проверка типов и семантики. Заполняет типы, слоты переменных, цели вызовов."""
from . import ast as A
from .diagnostics import CatError, CompileError
from ..core.cattypes import (BOOL, BY_NAME, ERR, I32, I64, STR, U8, U16, U32, U64,
                             VOID, max_of, min_of)

ARITH = {"+", "-", "*", "/", "%"}
SHIFT = {"<<", ">>"}
LOGIC = {"cat", "cats", "paw"}
EQ = {"==", "!="}
ORD = {"<", "<=", ">", ">="}
PEEK = {"peek8": U8, "peek16": U16, "peek32": U32, "peek64": U64}
POKE = {"poke8": U8, "poke16": U16, "poke32": U32, "poke64": U64}
BUILTINS = {"print", "write", "assert", "read_int", "input_ok", "rand"} | set(PEEK) | set(POKE)


def is_lit(e):
    if isinstance(e, A.IntLit):
        return True
    if isinstance(e, A.Unary):
        return is_lit(e.operand)
    if isinstance(e, A.Binary) and e.op not in EQ | ORD:
        return is_lit(e.left) and is_lit(e.right)
    return False


class Checker:
    def __init__(self, funcs, sources):
        self.funcs, self.sources, self.errors = {}, sources, []
        self.file = None
        for f in funcs:
            if f.name in self.funcs:
                self.error(f"function '{f.name}' is defined twice", f, f.file)
            elif f.name.split(".")[-1] in BUILTINS:
                self.error(f"'{f.name}' is a built-in name", f, f.file)
            else:
                self.funcs[f.name] = f
        self.list = funcs

    def error(self, msg, node, file=None):
        self.errors.append(CatError(msg, node.line, node.col, file or self.file))

    # --- типы ---
    def resolve(self, ref):
        t = BY_NAME.get(ref.name)
        if t is None:
            self.error(f"unknown type '{ref.name}'", ref)
            return ERR
        return t

    def run(self):
        for f in self.list:  # сигнатуры
            self.file = f.file
            f.param_types = [self.resolve(p.type) for p in f.params]
            f.ret_type = self.resolve(f.ret) if f.ret else VOID
        main = self.funcs.get("main")
        if main is None:
            self.errors.append(CatError("program has no 'fn main()'", 1, 1, self.list[0].file if self.list else None))
        else:
            self.file = main.file
            if main.params:
                self.error("'main' must not take parameters", main)
            if main.ret_type not in (VOID, I32, ERR):
                self.error("'main' must return nothing or i32", main)
        for f in self.list:
            self.check_func(f)
        if self.errors:
            raise CompileError(self.errors, self.sources)

    # --- функции ---
    def check_func(self, f):
        self.file, self.cur, self.scopes, self.nslots, self.loops = f.file, f, [{}], 0, 0
        for p, t in zip(f.params, f.param_types):
            self.declare(p.name, t, p)
        self.block(f.body)
        if f.ret_type not in (VOID, ERR) and not self.always_returns(f.body):
            self.error(f"function '{f.name}' may finish without returning a value", f)
        f.nlocals = self.nslots

    def declare(self, name, ty, node):
        if name in self.scopes[-1]:
            self.error(f"variable '{name}' is already declared in this scope", node)
        slot = self.nslots
        self.nslots += 1
        self.scopes[-1][name] = (ty, slot)
        return slot

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    def always_returns(self, node):
        if isinstance(node, A.Return):
            return True
        if isinstance(node, A.Block):
            return any(self.always_returns(s) for s in node.stmts)
        if isinstance(node, A.If):
            return node.other is not None and self.always_returns(node.then) and self.always_returns(node.other)
        return False

    # --- операторы ---
    def block(self, b):
        self.scopes.append({})
        for s in b.stmts:
            self.stmt(s)
        self.scopes.pop()

    def stmt(self, s):
        if isinstance(s, A.Let):
            if s.type:
                t = self.resolve(s.type)
                self.require(s.init, t)
            else:
                t = self.expr(s.init, None)
                if t in (VOID, STR):
                    self.error(f"cannot store a value of type '{t}' in a variable", s.init)
                    t = ERR
            s.slot = self.declare(s.name, t, s)  # объявляем ПОСЛЕ init
        elif isinstance(s, A.Assign):
            v = self.lookup(s.name)
            if v is None:
                self.error(f"undefined variable '{s.name}'", s)
                self.expr(s.value, None)
            else:
                s.slot = v[1]
                self.require(s.value, v[0])
        elif isinstance(s, A.If):
            self.require(s.cond, BOOL)
            self.block(s.then)
            if s.other:
                self.stmt(s.other)
        elif isinstance(s, A.While):
            self.require(s.cond, BOOL)
            self.loops += 1
            self.block(s.body)
            self.loops -= 1
        elif isinstance(s, A.For):
            self.for_stmt(s)
        elif isinstance(s, (A.Break, A.Continue)):
            if not self.loops:
                self.error(f"'{'break' if isinstance(s, A.Break) else 'continue'}' outside of a loop", s)
        elif isinstance(s, A.Return):
            rt = self.cur.ret_type
            if s.value is None:
                if rt not in (VOID, ERR):
                    self.error(f"'return' needs a value of type '{rt}'", s)
            elif rt is VOID:
                self.error("this function returns nothing, but 'return' has a value", s.value)
            else:
                self.require(s.value, rt)
        elif isinstance(s, A.Block):
            self.block(s)
        elif isinstance(s, A.ExprStmt):
            self.expr(s.expr, None)

    def for_stmt(self, s):
        if is_lit(s.start) and not is_lit(s.end):
            te = self.expr(s.end, None)
            ts = self.expr(s.start, te if te is not ERR else None)
        else:
            ts = self.expr(s.start, None)
            te = self.expr(s.end, ts if ts is not ERR else None)
        if ERR in (ts, te):
            ts = ERR
        elif not ts.is_int:
            self.error(f"'for' range must be integers, found '{ts}'", s.start)
            ts = ERR
        elif ts is not te:
            self.error(f"type mismatch in range: '{ts}'..'{te}'", s.end)
            ts = ERR
        s.ty = ts
        self.scopes.append({})
        s.slot = self.declare(s.var, ts, s)
        s.endslot = self.nslots
        self.nslots += 1
        self.loops += 1
        self.block(s.body)
        self.loops -= 1
        self.scopes.pop()

    # --- выражения ---
    def require(self, e, want):
        got = self.expr(e, want)
        if got is not want and got is not ERR and want is not ERR:
            self.error(f"type mismatch: expected '{want}', found '{got}'", e)
        return got

    def expr(self, e, hint):
        t = self._expr(e, hint)
        e.ty = t
        return t

    def _expr(self, e, hint):
        if isinstance(e, A.IntLit):
            t = hint if hint is not None and hint.is_int else I64
            if not (min_of(t) <= e.value <= max_of(t)):
                self.error(f"literal {e.value} does not fit in '{t}' ({min_of(t)}..{max_of(t)})", e)
                return ERR
            return t
        if isinstance(e, A.BoolLit):
            return BOOL
        if isinstance(e, A.StrLit):
            return STR
        if isinstance(e, A.Var):
            v = self.lookup(e.name)
            if v is None:
                self.error(f"undefined variable '{e.name}'", e)
                return ERR
            e.slot = v[1]
            return v[0]
        if isinstance(e, A.Unary):
            t = self.expr(e.operand, hint)
            if t is ERR:
                return ERR
            if e.op == "meow" and (t.is_int or t is BOOL):
                return t
            if e.op == "-" and t.is_int and t.signed:
                return t
            self.error(f"operator '{e.op}' cannot be applied to '{t}'", e)
            return ERR
        if isinstance(e, A.Cast):
            src = self.expr(e.operand, None)
            dst = self.resolve(e.target)
            if ERR in (src, dst):
                return ERR
            if dst is BOOL and src is not BOOL:
                self.error("cannot cast to 'bool'; use '!= 0' instead", e)
                return ERR
            if not (src.is_int or src is BOOL):
                self.error(f"cannot cast '{src}' to '{dst}'", e)
                return ERR
            return dst
        if isinstance(e, A.Binary):
            return self.binary(e, hint)
        if isinstance(e, A.Call):
            return self.call(e)
        raise AssertionError(e)

    def binary(self, e, hint):
        op = e.op
        h = None if op in EQ | ORD else hint
        l, r = e.left, e.right
        if is_lit(l) and not is_lit(r):
            tr = self.expr(r, h)
            tl = self.expr(l, tr if tr is not ERR else None)
        else:
            tl = self.expr(l, h)
            tr = self.expr(r, tl if tl is not ERR else None)
        if ERR in (tl, tr):
            return ERR
        if tl is not tr:
            self.error(f"type mismatch: '{tl}' {op} '{tr}' (use 'as' to convert)", e)
            return ERR
        if op in ("&&", "||") and tl is BOOL:
            return BOOL
        if op in ARITH | SHIFT and tl.is_int:
            return tl
        if op in LOGIC and (tl.is_int or tl is BOOL):
            return tl
        if op in EQ and (tl.is_int or tl is BOOL):
            return BOOL
        if op in ORD and tl.is_int:
            return BOOL
        self.error(f"operator '{op}' cannot be applied to '{tl}'", e)
        return ERR

    def call(self, e):
        name = e.name
        base = name.split(".")[-1]
        if name == base and base in BUILTINS:
            e.builtin, e.target = True, base
            return self.builtin(e)
        full = name
        if "." not in name and self.cur.module and f"{self.cur.module}.{name}" in self.funcs:
            full = f"{self.cur.module}.{name}"
        f = self.funcs.get(full)
        if f is None:
            self.error(f"undefined function '{name}'", e)
            for a in e.args:
                self.expr(a, None)
            return ERR
        e.target = full
        if len(e.args) != len(f.params):
            self.error(f"'{name}' takes {len(f.params)} argument(s), got {len(e.args)}", e)
            for a in e.args:
                self.expr(a, None)
        else:
            for a, t in zip(e.args, f.param_types):
                self.require(a, t)
        return f.ret_type

    def builtin(self, e):
        n, args = e.target, e.args

        def arity(k):
            if len(args) != k:
                self.error(f"'{n}' takes {k} argument(s), got {len(args)}", e)
                for a in args:
                    self.expr(a, None)
                return False
            return True

        if n == "read_int":
            arity(0)
            return I64
        if n == "input_ok":
            arity(0)
            return BOOL
        if n == "rand":
            if arity(1):
                self.require(args[0], U32)
            return U32
        if n in ("print", "write"):
            if arity(1):
                t = self.expr(args[0], None)
                if t not in (STR, BOOL, ERR) and not t.is_int:
                    self.error(f"cannot print a value of type '{t}'", args[0])
            return VOID
        if n == "assert":
            if arity(1):
                self.require(args[0], BOOL)
            return VOID
        if n in PEEK:
            if arity(1):
                self.require(args[0], U32)
            return PEEK[n]
        if arity(2):  # poke*
            self.require(args[0], U32)
            self.require(args[1], POKE[n])
        return VOID
