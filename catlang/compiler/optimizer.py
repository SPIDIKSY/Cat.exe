"""Оптимизатор: свёртка констант, удаление мёртвых веток и недостижимого кода.

Константы считаются тем же АЛУ, что и в виртуальной машине, поэтому
результат свёртки всегда совпадает с результатом выполнения.
"""
from . import ast as A
from ..core.alu import FastALU
from ..core.cattypes import BOOL

ALU = FastALU()
BIN = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "rem", "<<": "shl", ">>": "shr",
       "cat": "cat", "cats": "cats", "paw": "paw", "==": "eq", "!=": "ne",
       "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}


def lit(e):
    return isinstance(e, (A.IntLit, A.BoolLit))


def val(e):
    return int(e.value)


def mk(node, v, ty):
    if ty is BOOL:
        n = A.BoolLit(node.line, node.col, bool(v))
    else:
        n = A.IntLit(node.line, node.col, v)
    n.ty = ty
    return n


def fold_expr(e):
    if isinstance(e, A.Unary):
        e.operand = fold_expr(e.operand)
        if lit(e.operand):
            f = ALU.meow if e.op == "meow" else ALU.neg
            return mk(e, f(val(e.operand), e.ty), e.ty)
    elif isinstance(e, A.Cast):
        e.operand = fold_expr(e.operand)
        if lit(e.operand):
            return mk(e, ALU.cast(val(e.operand), e.ty), e.ty)
    elif isinstance(e, A.Binary):
        e.left, e.right = fold_expr(e.left), fold_expr(e.right)
        if e.op in ("&&", "||"):
            if isinstance(e.left, A.BoolLit):  # короткое вычисление известно заранее
                return e.left if e.left.value == (e.op == "||") else e.right
            return e
        if lit(e.left) and lit(e.right):
            a, b, t = val(e.left), val(e.right), e.left.ty
            if e.op in ("/", "%") and b == 0:
                return e  # ошибка времени выполнения, не трогаем
            if e.op in ("<<", ">>") and not 0 <= b < t.bits:
                return e
            return mk(e, getattr(ALU, BIN[e.op])(a, b, t), e.ty)
    elif isinstance(e, A.Call):
        e.args = [fold_expr(a) for a in e.args]
    elif isinstance(e, A.Field):
        e.base = fold_expr(e.base)
    elif isinstance(e, A.Index):
        e.base, e.index = fold_expr(e.base), fold_expr(e.index)
    elif isinstance(e, A.ArrayLit):
        e.elems = [fold_expr(a) for a in e.elems]
    elif isinstance(e, A.ArrayRepeat):
        e.value, e.count = fold_expr(e.value), fold_expr(e.count)
    return e


def fold_block(b):
    out = []
    for s in b.stmts:
        s = fold_stmt(s)
        if s is None:
            continue
        out.append(s)
        if isinstance(s, (A.Return, A.Break, A.Continue)):
            break  # дальше код недостижим
    b.stmts = out
    return b


def fold_stmt(s):
    if isinstance(s, (A.Let, A.Assign)):
        if isinstance(s, A.Let):
            s.init = fold_expr(s.init)
        else:
            s.value = fold_expr(s.value)
    elif isinstance(s, A.FieldAssign):
        s.base, s.value = fold_expr(s.base), fold_expr(s.value)
    elif isinstance(s, A.IndexAssign):
        s.base, s.index, s.value = fold_expr(s.base), fold_expr(s.index), fold_expr(s.value)
    elif isinstance(s, A.ExprStmt):
        s.expr = fold_expr(s.expr)
    elif isinstance(s, A.Return) and s.value is not None:
        s.value = fold_expr(s.value)
    elif isinstance(s, A.Block):
        return fold_block(s)
    elif isinstance(s, A.If):
        s.cond = fold_expr(s.cond)
        s.then = fold_block(s.then)
        if s.other:
            s.other = fold_stmt(s.other)
        if isinstance(s.cond, A.BoolLit):
            return s.then if s.cond.value else s.other
    elif isinstance(s, A.For):
        s.start, s.end = fold_expr(s.start), fold_expr(s.end)
        s.body = fold_block(s.body)
    elif isinstance(s, A.While):
        s.cond = fold_expr(s.cond)
        s.body = fold_block(s.body)
        if isinstance(s.cond, A.BoolLit) and not s.cond.value:
            return None
    return s


def optimize(funcs):
    for f in funcs:
        fold_block(f.body)
