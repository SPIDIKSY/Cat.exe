"""Узлы синтаксического дерева CAT. Поля, заполняемые проверкой типов, помечены (т)."""
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass(eq=False)
class Node:
    line: int
    col: int


@dataclass(eq=False)
class TypeRef(Node):
    name: str
    elem: Optional["TypeRef"] = None  # для массива [T]


# --- выражения ---
@dataclass(eq=False)
class Expr(Node):
    ty: Any = field(default=None, kw_only=True)  # (т)


@dataclass(eq=False)
class IntLit(Expr):
    value: int


@dataclass(eq=False)
class BoolLit(Expr):
    value: bool


@dataclass(eq=False)
class StrLit(Expr):
    value: str


@dataclass(eq=False)
class Var(Expr):
    name: str
    slot: int = field(default=-1, kw_only=True)  # (т)


@dataclass(eq=False)
class Unary(Expr):
    op: str  # 'meow' | '-'
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Cast(Expr):
    operand: Expr
    target: TypeRef


@dataclass(eq=False)
class Index(Expr):
    base: Expr
    index: Expr


@dataclass(eq=False)
class ArrayLit(Expr):
    elems: list
    tmp: int = field(default=-1, kw_only=True)  # (т) скрытая переменная для сборки


@dataclass(eq=False)
class ArrayRepeat(Expr):
    value: Expr
    count: Expr


@dataclass(eq=False)
class Call(Expr):
    name: str
    args: List[Expr]
    target: str = field(default="", kw_only=True)  # (т) полное имя функции или встроенной
    builtin: bool = field(default=False, kw_only=True)  # (т)


# --- операторы ---
@dataclass(eq=False)
class Block(Node):
    stmts: list


@dataclass(eq=False)
class Let(Node):
    name: str
    type: Optional[TypeRef]
    init: Expr
    slot: int = field(default=-1, kw_only=True)  # (т)


@dataclass(eq=False)
class Assign(Node):
    name: str
    value: Expr
    slot: int = field(default=-1, kw_only=True)  # (т)


@dataclass(eq=False)
class IndexAssign(Node):
    base: Expr
    index: Expr
    value: Expr


@dataclass(eq=False)
class If(Node):
    cond: Expr
    then: Block
    other: Optional[Node]  # Block | If | None


@dataclass(eq=False)
class While(Node):
    cond: Expr
    body: Block


@dataclass(eq=False)
class For(Node):
    var: str
    start: Expr
    end: Expr
    body: Block
    slot: int = field(default=-1, kw_only=True)     # (т)
    endslot: int = field(default=-1, kw_only=True)  # (т) скрытая переменная «конец»
    ty: Any = field(default=None, kw_only=True)     # (т)


@dataclass(eq=False)
class Break(Node):
    pass


@dataclass(eq=False)
class Continue(Node):
    pass


@dataclass(eq=False)
class Return(Node):
    value: Optional[Expr]


@dataclass(eq=False)
class ExprStmt(Node):
    expr: Expr


# --- верхний уровень ---
@dataclass(eq=False)
class Param(Node):
    name: str
    type: TypeRef


@dataclass(eq=False)
class Func(Node):
    name: str
    params: List[Param]
    ret: Optional[TypeRef]
    body: Block
    file: Optional[str] = None
    module: str = ""
    nlocals: int = field(default=0, kw_only=True)  # (т)


@dataclass(eq=False)
class Use(Node):
    name: str


@dataclass(eq=False)
class Program:
    uses: List[Use]
    funcs: List[Func]
