"""Проверка типов и семантики. Заполняет типы, слоты переменных, цели вызовов."""
from dataclasses import dataclass

from . import ast as A
from .diagnostics import CatError, CompileError
from .vocab import shown
from ..core.cattypes import (BOOL, BY_NAME, ERR, I32, I64, STR, U8, U16, U32, U64,
                             NIL, Type, VOID, array_of, esize, max_of, min_of, reset_array_types)

ARITH = {"+", "-", "*", "/", "%"}
SHIFT = {"<<", ">>"}
LOGIC = {"cat", "cats", "paw"}
EQ = {"==", "!="}
ORD = {"<", "<=", ">", ">="}
PEEK = {"look8": U8, "look16": U16, "look32": U32, "look64": U64}
POKE = {"bat8": U8, "bat16": U16, "bat32": U32, "bat64": U64}
INTRINSICS = {"__write", "__read", "__exit", "__mem", "__rdtsc", "__trap"}  # только для рантайма (stdlib/rt.cat)
BUILTINS = {"meow", "mew", "claw", "ask", "heard", "roll", "stretch", "scribble", "listen", "bury"} | INTRINSICS | set(PEEK) | set(POKE)


def is_lit(e):
    if isinstance(e, A.IntLit):
        return True
    if isinstance(e, A.Unary):
        return is_lit(e.operand)
    if isinstance(e, A.Binary) and e.op not in EQ | ORD:
        return is_lit(e.left) and is_lit(e.right)
    return False


@dataclass
class StructInfo:
    name: str
    type: Type
    fields: list      # (имя, тип, смещение)
    size: int = 0


class Checker:
    def __init__(self, funcs, sources, structs=()):
        reset_array_types()
        self.funcs, self.sources, self.errors = {}, sources, []
        self.file = None
        self.structs, self.struct_decls = {}, list(structs)
        for sd in self.struct_decls:  # шаг 1: регистрируем имена (структуры могут ссылаться друг на друга)
            if sd.name in BY_NAME or sd.name in self.structs:
                self.error(f"type '{sd.name}' is defined twice or is a built-in type", sd, sd.file)
            else:
                self.structs[sd.name] = StructInfo(sd.name, Type(sd.name, 32, False, 254, ref="struct"), [])
        for f in funcs:
            if f.name in self.structs:
                self.error(f"'{f.name}' is already used as a structure name", f, f.file)
            elif f.name in self.funcs:
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
        if ref.elem is not None:
            inner = self.resolve(ref.elem)
            return ERR if inner is ERR else array_of(inner)
        t = BY_NAME.get(ref.name)
        if t is None and ref.name in self.structs:
            return self.structs[ref.name].type
        if t is None:
            self.error(f"unknown type '{ref.name}'", ref)
            return ERR
        return t

    def layout(self):
        """Шаг 2: поля структур. Каждое поле выровнено по своему размеру, размер объекта кратен 8."""
        for sd in self.struct_decls:
            info = self.structs.get(sd.name)
            if info is None or info.fields:
                continue
            self.file, off, seen = sd.file, 0, set()
            for p in sd.fields:
                ft = self.resolve(p.type)
                if p.name in seen:
                    self.error(f"field '{p.name}' is defined twice", p)
                seen.add(p.name)
                sz = esize(ft) if ft is not ERR else 1
                off = (off + sz - 1) // sz * sz
                info.fields.append((p.name, ft, off))
                off += sz
            info.size = (off + 7) // 8 * 8

    def run(self):
        self.layout()
        for f in self.list:  # сигнатуры
            self.file = f.file
            f.param_types = [self.resolve(p.type) for p in f.params]
            f.ret_type = self.resolve(f.ret) if f.ret else VOID
        main = self.funcs.get("main")
        if main is None:
            self.errors.append(CatError(f"program has no '{shown('fn')} main()'", 1, 1, self.list[0].file if self.list else None))
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
                if t is NIL:
                    self.error(f"cannot infer the type of '{shown('nil')}'; write the type after the name", s.init)
                    t = ERR
                elif t is VOID:
                    self.error("cannot store a value of type 'void' in a variable", s.init)
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
        elif isinstance(s, A.IndexAssign):
            tb = self.expr(s.base, None)
            self.require(s.index, U32)
            if tb is ERR:
                self.expr(s.value, None)
            elif tb.ref == "array":
                self.require(s.value, tb.elem)
            else:
                self.error("strings are immutable" if tb is STR else f"cannot index a value of type '{tb}'", s)
                self.expr(s.value, None)
        elif isinstance(s, A.FieldAssign):
            ft = self.field_of(s, s.base, s.name)
            if ft is ERR:
                self.expr(s.value, None)
            else:
                s.fty = ft
                self.require(s.value, ft)
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
                self.error(f"'{shown('break') if isinstance(s, A.Break) else shown('continue')}' outside of a loop", s)
        elif isinstance(s, A.Return):
            rt = self.cur.ret_type
            if s.value is None:
                if rt not in (VOID, ERR):
                    self.error(f"'{shown('return')}' needs a value of type '{rt}'", s)
            elif rt is VOID:
                self.error(f"this function returns nothing, but '{shown('return')}' has a value", s.value)
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
            self.error(f"'{shown('for')}' range must be integers, found '{ts}'", s.start)
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
            self.error(f"operator '{shown(e.op)}' cannot be applied to '{t}'", e)
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
        if isinstance(e, A.Nil):
            return hint if hint is not None and hint.ref else NIL
        if isinstance(e, A.Field):
            return self.field_of(e, e.base, e.name)
        if isinstance(e, A.Index):
            tb = self.expr(e.base, None)
            self.require(e.index, U32)
            if tb is ERR:
                return ERR
            if tb.ref == "array":
                return tb.elem
            if tb is STR:
                return U8
            self.error(f"cannot index a value of type '{tb}'", e)
            return ERR
        if isinstance(e, (A.ArrayLit, A.ArrayRepeat)):
            return self.array_expr(e, hint)
        if isinstance(e, A.Call):
            return self.call(e)
        raise AssertionError(e)

    def field_of(self, node, base, name):
        """Тип поля `base.name`; записывает смещение в узел."""
        tb = self.expr(base, None)
        if tb is ERR:
            return ERR
        info = self.structs.get(tb.name) if tb.ref == "struct" else None
        if info is None:
            self.error(f"'{tb}' has no fields", node)
            return ERR
        for fname, ft, off in info.fields:
            if fname == name:
                node.off = off
                return ft
        self.error(f"structure '{info.name}' has no field '{name}'", node)
        return ERR

    def array_expr(self, e, hint):
        eh = hint.elem if hint is not None and hint.ref == "array" else None
        if isinstance(e, A.ArrayRepeat):
            t = self.expr(e.value, eh)
            self.require(e.count, U32)
        elif not e.elems:
            if eh is None:
                self.error("cannot infer the element type of an empty array", e)
                return ERR
            t = eh
        else:
            t = self.expr(e.elems[0], eh)
            for el in e.elems[1:]:
                self.require(el, t)
        if t is NIL:
            self.error(f"cannot infer the type of '{shown('nil')}' elements", e)
            return ERR
        if t is VOID:
            self.error("array elements cannot be 'void'", e)
            return ERR
        if t is ERR:
            return ERR
        if isinstance(e, A.ArrayLit):
            e.tmp = self.nslots
            self.nslots += 1
        return array_of(t)

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
        if tl is NIL and tr.ref:
            e.left.ty = tl = tr
        elif tr is NIL and tl.ref:
            e.right.ty = tr = tl
        if tl is not tr:
            self.error(f"type mismatch: '{tl}' {shown(op)} '{tr}' (use '{shown('as')}' to convert)", e)
            return ERR
        if op in ("&&", "||") and tl is BOOL:
            return BOOL
        if tl.ref in ("array", "struct") and op in EQ:
            return BOOL  # сравниваются адреса: «тот же самый объект»
        if tl is STR and op == "+":
            return STR
        if tl is STR and op in EQ:
            return BOOL
        if op in ARITH | SHIFT and tl.is_int:
            return tl
        if op in LOGIC and (tl.is_int or tl is BOOL):
            return tl
        if op in EQ and (tl.is_int or tl is BOOL):
            return BOOL
        if op in ORD and tl.is_int:
            return BOOL
        self.error(f"operator '{shown(op)}' cannot be applied to '{tl}'", e)
        return ERR

    def call(self, e):
        name = e.name
        base = name.split(".")[-1]
        if name == base and base in BUILTINS:
            e.builtin, e.target = True, base
            return self.builtin(e)
        if name in self.structs:
            return self.constructor(e, self.structs[name])
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

    def constructor(self, e, info):
        if len(e.args) != len(info.fields):
            self.error(f"'{info.name}' has {len(info.fields)} field(s), got {len(e.args)} value(s)", e)
            for a in e.args:
                self.expr(a, None)
        else:
            for a, (_, ft, _) in zip(e.args, info.fields):
                self.require(a, ft)
        e.struct, e.tmp = info, self.nslots
        self.nslots += 1
        return info.type

    def builtin(self, e):
        n, args = e.target, e.args

        def arity(k):
            if len(args) != k:
                self.error(f"'{n}' takes {k} argument(s), got {len(args)}", e)
                for a in args:
                    self.expr(a, None)
                return False
            return True

        if n == "ask":
            arity(0)
            return I64
        if n == "heard":
            arity(0)
            return BOOL
        if n == "roll":
            if arity(1):
                self.require(args[0], U32)
            return U32
        if n in ("meow", "mew"):
            if arity(1):
                t = self.expr(args[0], None)
                if t not in (STR, BOOL, ERR) and not t.is_int:
                    self.error(f"cannot print a value of type '{t}'", args[0])
            return VOID
        if n == "claw":
            if arity(1):
                self.require(args[0], BOOL)
            return VOID
        if n in INTRINSICS:
            sig = {"__write": ([I64, U64, U64], I64), "__read": ([I64, U64, U64], I64), "__exit": ([I64], VOID),
                   "__mem": ([], U64), "__rdtsc": ([], U64), "__trap": ([I64], VOID)}[n]
            if arity(len(sig[0])):
                for a, t in zip(args, sig[0]):
                    self.require(a, t)
            return sig[1]
        if n == "bury":
            if arity(1):
                t = self.expr(args[0], None)
                if not t.ref and t is not ERR:
                    self.error(f"'bury' needs an array, string or structure, found '{t}'", args[0])
            return VOID
        if n == "stretch":
            if arity(1):
                t = self.expr(args[0], None)
                if t is not STR and t.ref != "array" and t is not ERR:
                    self.error(f"'stretch' needs an array or a string, found '{t}'", args[0])
            return U32
        if n == "scribble":
            if arity(1):
                t = self.expr(args[0], None)
                if not t.is_int and t is not ERR:
                    self.error(f"'scribble' needs an integer, found '{t}'", args[0])
            return STR
        if n == "listen":
            arity(0)
            return STR
        if n in PEEK:
            if arity(1):
                self.require(args[0], U32)
            return PEEK[n]
        if arity(2):  # poke*
            self.require(args[0], U32)
            self.require(args[1], POKE[n])
        return VOID
