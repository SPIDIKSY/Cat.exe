"""Набор инструкций CAT-VM. Подробности — docs/BYTECODE.md.

Форматы операндов: ''  нет | 'ty' тип (1 байт) | 'tyimm' тип + 8 байт
                   'u16'  | 'u32'. Все числа little-endian.
"""
import struct

from ..core.cattypes import BY_CODE, wrap

# имя: (код, формат)
OPS = {
    "HALT": (0x00, ""),
    "PUSH": (0x01, "tyimm"), "POP": (0x02, ""), "DUP": (0x03, ""),
    "LOAD": (0x10, "u16"), "STORE": (0x11, "u16"),
    # логическое ядро
    "CAT": (0x20, "ty"), "CATS": (0x21, "ty"), "PAW": (0x22, "ty"), "MEOW": (0x23, "ty"),
    # арифметика и сдвиги
    "ADD": (0x30, "ty"), "SUB": (0x31, "ty"), "MUL": (0x32, "ty"), "DIV": (0x33, "ty"),
    "REM": (0x34, "ty"), "NEG": (0x35, "ty"), "SHL": (0x36, "ty"), "SHR": (0x37, "ty"),
    # сравнения
    "EQ": (0x40, "ty"), "NE": (0x41, "ty"), "LT": (0x42, "ty"),
    "LE": (0x43, "ty"), "GT": (0x44, "ty"), "GE": (0x45, "ty"),
    "CAST": (0x50, "ty"),
    # управление
    "JMP": (0x60, "u32"), "JZ": (0x61, "u32"), "JNZ": (0x62, "u32"),
    "CALL": (0x70, "u16"), "RET": (0x71, ""), "RETV": (0x72, ""),
    # ввод-вывод, память, проверки
    "PRINTI": (0x80, ""), "PRINTB": (0x81, ""), "PRINTS": (0x82, "u16"),
    "LOADM": (0x90, "ty"), "STOREM": (0x91, "ty"),
    "WRITEI": (0x83, ""), "WRITEB": (0x84, ""), "WRITES": (0x85, "u16"),
    "READI": (0x86, ""), "INOK": (0x87, ""), "RAND": (0x88, ""),
    "ASSERT": (0xA0, ""),
    # массивы и строки (значение — адрес объекта в куче)
    "ALOAD": (0xB0, "ty"), "ASTORE": (0xB1, "ty"), "ALEN": (0xB2, ""), "NEWARR": (0xB3, "ty"),
    "STR": (0xB4, "u16"), "SCAT": (0xB5, ""), "STREQ": (0xB6, ""), "ITOS": (0xB7, ""),
    "READS": (0xB8, ""), "PRINTV": (0xB9, ""), "WRITEV": (0xBA, ""),
    # структуры и освобождение памяти
    "NEWS": (0xBB, "u16"), "FLOAD": (0xBC, "tyu16"), "FSTORE": (0xBD, "tyu16"), "FREE": (0xBE, ""),
}
BY_OPCODE = {code: (name, fmt) for name, (code, fmt) in OPS.items()}
SIZE = {"": 1, "ty": 2, "tyu16": 4, "tyimm": 10, "u16": 3, "u32": 5}
TERMINATORS = {"RET", "RETV", "JMP", "HALT"}
JUMPS = {"JMP", "JZ", "JNZ"}


def encode(name, arg, ty):
    code, fmt = OPS[name]
    if fmt == "":
        return bytes([code])
    if fmt == "ty":
        return bytes([code, ty])
    if fmt == "tyu16":
        return struct.pack("<BBH", code, ty, arg)
    if fmt == "tyimm":
        return struct.pack("<BBQ", code, ty, arg & 0xFFFFFFFFFFFFFFFF)
    return struct.pack("<B" + ("H" if fmt == "u16" else "I"), code, arg)


class DecodeError(Exception):
    pass


def decode(code):
    """bytes -> список (адрес, имя, arg, ty). arg для PUSH уже каноническое значение."""
    out, pc, n = [], 0, len(code)
    while pc < n:
        entry = BY_OPCODE.get(code[pc])
        if entry is None:
            raise DecodeError(f"unknown opcode 0x{code[pc]:02X} at 0x{pc:04X}")
        name, fmt = entry
        size = SIZE[fmt]
        if pc + size > n:
            raise DecodeError(f"truncated instruction at 0x{pc:04X}")
        arg = ty = None
        if fmt == "ty":
            ty = code[pc + 1]
        elif fmt == "tyu16":
            ty = code[pc + 1]
            arg = struct.unpack_from("<H", code, pc + 2)[0]
        elif fmt == "tyimm":
            ty = code[pc + 1]
            arg = struct.unpack_from("<Q", code, pc + 2)[0]
        elif fmt == "u16":
            arg = struct.unpack_from("<H", code, pc + 1)[0]
        elif fmt == "u32":
            arg = struct.unpack_from("<I", code, pc + 1)[0]
        if ty is not None:
            if ty not in BY_CODE:
                raise DecodeError(f"bad type code {ty} at 0x{pc:04X}")
            if fmt == "tyimm":
                arg = wrap(arg, BY_CODE[ty])
        out.append((pc, name, arg, ty))
        pc += size
    return out
