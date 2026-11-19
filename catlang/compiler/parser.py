"""Парсер CAT (рекурсивный спуск). Грамматика — docs/GRAMMAR.md."""
from . import ast as A
from .diagnostics import CatError
from .lexer import tokenize
from .vocab import shown

# Приоритеты бинарных операций: от низкого к высокому
LEVELS = [{"||"}, {"&&"}, {"cats"}, {"paw"}, {"cat"}, {"==", "!="}, {"<", "<=", ">", ">="},
          {"<<", ">>"}, {"+", "-"}, {"*", "/", "%"}]


class Parser:
    def __init__(self, toks, file):
        self.t, self.i, self.file = toks, 0, file

    # --- помощники ---
    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def is_(self, kind, value=None, k=0):
        tok = self.peek(k)
        return tok.kind == kind and (value is None or tok.value == value)

    def err(self, msg, tok=None):
        tok = tok or self.peek()
        raise CatError(msg, tok.line, tok.col, self.file)

    def expect(self, kind, value=None, what=None):
        if not self.is_(kind, value):
            tok = self.peek()
            found = "end of file" if tok.kind == "eof" else f"'{shown(tok.value)}'"
            want = what or f"'{shown(value)}'" if value else what or kind
            self.err(f"expected {want}, found {found}")
        return self.next()

    def accept(self, kind, value):
        if self.is_(kind, value):
            return self.next()
        return None

    # --- верхний уровень ---
    def program(self):
        uses, funcs = [], []
        while not self.is_("eof"):
            if self.is_("kw", "use"):
                t = self.next()
                name = self.expect("id", what="module name").value
                self.expect("op", ";")
                uses.append(A.Use(t.line, t.col, name))
            elif self.is_("kw", "fn"):
                funcs.append(self.func())
            else:
                self.err(f"expected '{shown('fn')}' or '{shown('use')}' at top level")
        return A.Program(uses, funcs)

    def type_ref(self):
        if self.is_("op", "["):
            b = self.next()
            inner = self.type_ref()
            self.expect("op", "]")
            return A.TypeRef(b.line, b.col, f"[{inner.name}]", inner)
        t = self.expect("id", what="type name")
        return A.TypeRef(t.line, t.col, t.value)

    def func(self):
        kw = self.expect("kw", "fn")
        name = self.expect("id", what="function name")
        self.expect("op", "(")
        params = []
        if not self.is_("op", ")"):
            while True:
                p = self.expect("id", what="parameter name")
                self.expect("op", ":")
                params.append(A.Param(p.line, p.col, p.value, self.type_ref()))
                if not self.accept("op", ","):
                    break
        self.expect("op", ")")
        ret = self.type_ref() if self.accept("op", "->") else None
        return A.Func(kw.line, kw.col, name.value, params, ret, self.block(), self.file)

    # --- операторы ---
    def block(self):
        b = self.expect("op", "{")
        stmts = []
        while not self.is_("op", "}"):
            if self.is_("eof"):
                self.err("unexpected end of file, '}' is missing", b)
            stmts.append(self.stmt())
        self.next()
        return A.Block(b.line, b.col, stmts)

    def stmt(self):
        t = self.peek()
        if self.is_("kw", "let"):
            self.next()
            name = self.expect("id", what="variable name").value
            ty = self.type_ref() if self.accept("op", ":") else None
            self.expect("op", "=")
            init = self.expr()
            self.expect("op", ";")
            return A.Let(t.line, t.col, name, ty, init)
        if self.is_("kw", "if"):
            return self.if_stmt()
        if self.is_("kw", "while"):
            self.next()
            cond = self.expr()
            return A.While(t.line, t.col, cond, self.block())
        if self.is_("kw", "for"):
            self.next()
            name = self.expect("id", what="loop variable").value
            self.expect("kw", "in")
            start = self.expr()
            self.expect("op", "..")
            end = self.expr()
            return A.For(t.line, t.col, name, start, end, self.block())
        if self.is_("kw", "break") or self.is_("kw", "continue"):
            self.next()
            self.expect("op", ";")
            return (A.Break if t.value == "break" else A.Continue)(t.line, t.col)
        if self.is_("kw", "return"):
            self.next()
            val = None if self.is_("op", ";") else self.expr()
            self.expect("op", ";")
            return A.Return(t.line, t.col, val)
        if self.is_("op", "{"):
            return self.block()
        if self.is_("id") and self.is_("op", "=", 1):
            self.next()
            self.next()
            val = self.expr()
            self.expect("op", ";")
            return A.Assign(t.line, t.col, t.value, val)
        e = self.expr()
        if self.is_("op", "="):
            if not isinstance(e, A.Index):
                self.err("only a variable or an array element can be assigned")
            self.next()
            val = self.expr()
            self.expect("op", ";")
            return A.IndexAssign(t.line, t.col, e.base, e.index, val)
        self.expect("op", ";")
        return A.ExprStmt(t.line, t.col, e)

    def if_stmt(self):
        t = self.expect("kw", "if")
        cond = self.expr()
        then = self.block()
        other = None
        if self.accept("kw", "else"):
            other = self.if_stmt() if self.is_("kw", "if") else self.block()
        return A.If(t.line, t.col, cond, then, other)

    # --- выражения ---
    def expr(self):
        return self.binary(0)

    def binary(self, level):
        if level == len(LEVELS):
            return self.cast()
        left = self.binary(level + 1)
        while self.peek().kind in ("op", "kw") and self.peek().value in LEVELS[level]:
            op = self.next()
            right = self.binary(level + 1)
            left = A.Binary(op.line, op.col, op.value, left, right)
        return left

    def cast(self):
        e = self.unary()
        while self.is_("kw", "as"):
            t = self.next()
            e = A.Cast(t.line, t.col, e, self.type_ref())
        return e

    def unary(self):
        t = self.peek()
        if self.is_("kw", "meow"):
            self.next()
            return A.Unary(t.line, t.col, "meow", self.unary())
        if self.is_("op", "-"):
            self.next()
            if self.is_("int"):
                return A.IntLit(t.line, t.col, -self.next().value)
            return A.Unary(t.line, t.col, "-", self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while self.is_("op", "["):
            b = self.next()
            idx = self.expr()
            self.expect("op", "]")
            e = A.Index(b.line, b.col, e, idx)
        return e

    def primary(self):
        t = self.next()
        if t.kind == "op" and t.value == "[":
            if self.accept("op", "]"):
                return A.ArrayLit(t.line, t.col, [])
            first = self.expr()
            if self.accept("op", ";"):
                n = self.expr()
                self.expect("op", "]")
                return A.ArrayRepeat(t.line, t.col, first, n)
            elems = [first]
            while self.accept("op", ","):
                elems.append(self.expr())
            self.expect("op", "]")
            return A.ArrayLit(t.line, t.col, elems)
        if t.kind == "int":
            return A.IntLit(t.line, t.col, t.value)
        if t.kind == "str":
            return A.StrLit(t.line, t.col, t.value)
        if t.kind == "kw" and t.value in ("true", "false"):
            return A.BoolLit(t.line, t.col, t.value == "true")
        if t.kind == "op" and t.value == "(":
            e = self.expr()
            self.expect("op", ")")
            return e
        if t.kind == "id":
            name = t.value
            if self.is_("op", ".") and self.is_("id", k=1):
                self.next()
                name += "." + self.next().value
            if self.accept("op", "("):
                args = []
                if not self.is_("op", ")"):
                    while True:
                        args.append(self.expr())
                        if not self.accept("op", ","):
                            break
                self.expect("op", ")")
                return A.Call(t.line, t.col, name, args)
            return A.Var(t.line, t.col, name)
        self.i -= 1
        found = "end of file" if t.kind == "eof" else f"'{shown(t.value)}'"
        self.err(f"expected expression, found {found}", t)


def parse(src, file=None):
    return Parser(tokenize(src, file), file).program()
