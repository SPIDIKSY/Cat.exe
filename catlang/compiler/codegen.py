"""Кодогенератор: типизированное дерево -> IR (линейный список инструкций с метками)
-> ассемблер -> Program (байткод)."""
from collections import namedtuple

from . import ast as A
from ..core.cattypes import BOOL, STR
from ..vm.format import Debug, FuncInfo, Program
from ..vm.opcodes import OPS, SIZE, encode

Ins = namedtuple("Ins", "op arg ty line")  # op == 'LABEL' — метка (arg = имя)

BIN = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "REM", "<<": "SHL", ">>": "SHR",
       "cat": "CAT", "cats": "CATS", "paw": "PAW", "==": "EQ", "!=": "NE",
       "<": "LT", "<=": "LE", ">": "GT", ">=": "GE"}
CMP = {"==", "!=", "<", "<=", ">", ">="}


class Gen:
    def __init__(self, funcs):
        self.funcs = {f.name: f for f in funcs}
        self.order = []      # имена в порядке индексов
        self.index = {}
        self.consts, self.const_ix = [], {}
        self.labels = 0
        self.irs = {}
        self.loops = []  # (метка continue, метка break)

    def func_index(self, name):
        if name not in self.index:
            self.index[name] = len(self.order)
            self.order.append(name)
        return self.index[name]

    def const(self, s):
        if s not in self.const_ix:
            self.const_ix[s] = len(self.consts)
            self.consts.append(s)
        return self.const_ix[s]

    def run(self):
        self.func_index("main")
        i = 0
        while i < len(self.order):  # только достижимые из main функции
            f = self.funcs[self.order[i]]
            self.out = []
            self.block(f.body)
            if f.ret_type.bits == 0:
                self.emit("RETV", line=f.line)
            else:
                self.emit("PUSH", 0, f.ret_type, f.line)
                self.emit("RET", line=f.line)
            self.irs[f.name] = self.out
            i += 1
        return self.irs

    def emit(self, op, arg=None, ty=None, line=0):
        self.out.append(Ins(op, arg, ty.code if ty is not None else None, line))

    def label(self):
        self.labels += 1
        return f".L{self.labels}"

    # --- операторы ---
    def block(self, b):
        for s in b.stmts:
            self.stmt(s)

    def stmt(self, s):
        ln = s.line
        if isinstance(s, A.Let):
            self.expr(s.init)
            self.emit("STORE", s.slot, line=ln)
        elif isinstance(s, A.Assign):
            self.expr(s.value)
            self.emit("STORE", s.slot, line=ln)
        elif isinstance(s, A.If):
            els, end = self.label(), self.label()
            self.expr(s.cond)
            self.emit("JZ", els, line=ln)
            self.block(s.then)
            if s.other:
                self.emit("JMP", end, line=ln)
            self.emit("LABEL", els)
            if s.other:
                self.stmt(s.other)
                self.emit("LABEL", end)
        elif isinstance(s, A.While):
            top, end = self.label(), self.label()
            self.emit("LABEL", top)
            self.expr(s.cond)
            self.emit("JZ", end, line=ln)
            self.loops.append((top, end))
            self.block(s.body)
            self.loops.pop()
            self.emit("JMP", top, line=ln)
            self.emit("LABEL", end)
        elif isinstance(s, A.For):
            top, cont, end = self.label(), self.label(), self.label()
            self.expr(s.start)
            self.emit("STORE", s.slot, line=ln)
            self.expr(s.end)
            self.emit("STORE", s.endslot, line=ln)
            self.emit("LABEL", top)
            self.emit("LOAD", s.slot, line=ln)
            self.emit("LOAD", s.endslot, line=ln)
            self.emit("LT", ty=s.ty, line=ln)
            self.emit("JZ", end, line=ln)
            self.loops.append((cont, end))
            self.block(s.body)
            self.loops.pop()
            self.emit("LABEL", cont)
            self.emit("LOAD", s.slot, line=ln)
            self.emit("PUSH", 1, s.ty, ln)
            self.emit("ADD", ty=s.ty, line=ln)
            self.emit("STORE", s.slot, line=ln)
            self.emit("JMP", top, line=ln)
            self.emit("LABEL", end)
        elif isinstance(s, A.Break):
            self.emit("JMP", self.loops[-1][1], line=ln)
        elif isinstance(s, A.Continue):
            self.emit("JMP", self.loops[-1][0], line=ln)
        elif isinstance(s, A.Return):
            if s.value is not None:
                self.expr(s.value)
                self.emit("RET", line=ln)
            else:
                self.emit("RETV", line=ln)
        elif isinstance(s, A.Block):
            self.block(s)
        elif isinstance(s, A.ExprStmt):
            self.expr(s.expr)
            if s.expr.ty.bits != 0 and s.expr.ty is not STR:
                self.emit("POP", line=ln)

    # --- выражения ---
    def expr(self, e):
        ln = e.line
        if isinstance(e, (A.IntLit, A.BoolLit)):
            self.emit("PUSH", int(e.value), e.ty, ln)
        elif isinstance(e, A.Var):
            self.emit("LOAD", e.slot, line=ln)
        elif isinstance(e, A.Unary):
            self.expr(e.operand)
            self.emit("MEOW" if e.op == "meow" else "NEG", ty=e.ty, line=ln)
        elif isinstance(e, A.Cast):
            self.expr(e.operand)
            self.emit("CAST", ty=e.ty, line=ln)
        elif isinstance(e, A.Binary) and e.op in ("&&", "||"):
            skip, end = self.label(), self.label()
            self.expr(e.left)
            self.emit("JZ" if e.op == "&&" else "JNZ", skip, line=ln)
            self.expr(e.right)
            self.emit("JMP", end, line=ln)
            self.emit("LABEL", skip)
            self.emit("PUSH", int(e.op == "||"), BOOL, ln)
            self.emit("LABEL", end)
        elif isinstance(e, A.Binary):
            self.expr(e.left)
            self.expr(e.right)
            # для сравнений тип операции — тип операндов
            self.emit(BIN[e.op], ty=e.left.ty if e.op in CMP else e.ty, line=ln)
        elif isinstance(e, A.Call):
            self.call(e)
        else:
            raise AssertionError(e)

    def call(self, e):
        ln, n = e.line, e.target
        if not e.builtin:
            for a in e.args:
                self.expr(a)
            self.emit("CALL", self.func_index(n), line=ln)
        elif n in ("meow", "mew"):
            a, p = e.args[0], ("PRINT" if n == "meow" else "WRITE")
            if isinstance(a, A.StrLit):
                self.emit(p + "S", self.const(a.value), line=ln)
            else:
                self.expr(a)
                self.emit(p + ("B" if a.ty is BOOL else "I"), line=ln)
        elif n in ("ask", "heard", "roll"):
            for a in e.args:
                self.expr(a)
            self.emit({"ask": "READI", "heard": "INOK", "roll": "RAND"}[n], line=ln)
        elif n == "claw":
            self.expr(e.args[0])
            self.emit("ASSERT", line=ln)
        elif n.startswith("look"):
            self.expr(e.args[0])
            self.emit("LOADM", ty=e.ty, line=ln)
        else:  # poke
            self.expr(e.args[0])
            self.expr(e.args[1])
            self.emit("STOREM", ty=e.args[1].ty, line=ln)


def generate(funcs, strip=False, file=""):
    g = Gen(funcs)
    irs = g.run()
    # проход 1: адреса меток и начала функций
    pc, entries, labels = 0, [], {}
    for name in g.order:
        entries.append(pc)
        for ins in irs[name]:
            if ins.op == "LABEL":
                labels[ins.arg] = pc
            else:
                pc += SIZE[OPS[ins.op][1]]
    # проход 2: машинный код и таблица строк
    code, lines, last = bytearray(), [], None
    for name in g.order:
        for ins in irs[name]:
            if ins.op == "LABEL":
                continue
            if ins.line and ins.line != last:
                lines.append((len(code), ins.line))
                last = ins.line
            arg = labels[ins.arg] if ins.op in ("JMP", "JZ", "JNZ") else ins.arg
            code += encode(ins.op, arg, ins.ty)
    infos = [FuncInfo(entries[i], len(g.funcs[n].params), g.funcs[n].nlocals)
             for i, n in enumerate(g.order)]
    debug = None if strip else Debug(file, list(g.order), lines)
    return Program(g.consts, infos, bytes(code), 0, debug)
