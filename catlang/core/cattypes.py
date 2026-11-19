"""Типы CAT. Общие для компилятора и виртуальной машины."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    name: str
    bits: int
    signed: bool
    code: int  # номер типа в байткоде

    @property
    def mask(self):
        return (1 << self.bits) - 1

    @property
    def is_int(self):
        return self.bits > 1

    def __str__(self):
        return self.name


BOOL = Type("bool", 1, False, 0)
U8 = Type("u8", 8, False, 1)
U16 = Type("u16", 16, False, 2)
U32 = Type("u32", 32, False, 3)
U64 = Type("u64", 64, False, 4)
I8 = Type("i8", 8, True, 5)
I16 = Type("i16", 16, True, 6)
I32 = Type("i32", 32, True, 7)
I64 = Type("i64", 64, True, 8)

# Служебные типы компилятора (в байткоде не встречаются)
VOID = Type("void", 0, False, 250)
STR = Type("str", 0, False, 251)
ERR = Type("<error>", 0, False, 252)

TYPES = (BOOL, U8, U16, U32, U64, I8, I16, I32, I64)
BY_NAME = {t.name: t for t in TYPES}
BY_CODE = {t.code: t for t in TYPES}


def wrap(v, t):
    """Привести целое к каноническому виду типа t (оборачивание по модулю 2^bits)."""
    v &= t.mask
    if t.signed and v >> (t.bits - 1):
        v -= 1 << t.bits
    return v


def min_of(t):
    return -(1 << (t.bits - 1)) if t.signed else 0


def max_of(t):
    return (1 << (t.bits - 1)) - 1 if t.signed else (1 << t.bits) - 1
