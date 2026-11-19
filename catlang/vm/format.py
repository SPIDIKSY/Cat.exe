"""Формат файла .catc (байткод CAT). Описание — docs/BYTECODE.md."""
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .opcodes import JUMPS, TERMINATORS, DecodeError, decode

MAGIC = b"CATB"
VERSION = 1
FLAG_DEBUG = 1
S_CONST, S_FUNC, S_CODE, S_DEBUG = 1, 2, 3, 4


class FormatError(Exception):
    pass


def _make_table():
    t = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC = _make_table()


def crc32(data):
    c = 0xFFFFFFFF
    for b in data:
        c = _CRC[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


@dataclass
class FuncInfo:
    entry: int
    nargs: int
    nlocals: int


@dataclass
class Debug:
    file: str = ""
    names: List[str] = field(default_factory=list)
    lines: List[Tuple[int, int]] = field(default_factory=list)  # (pc, строка)


@dataclass
class Program:
    consts: List[str]
    funcs: List[FuncInfo]
    code: bytes
    entry: int = 0
    debug: Optional[Debug] = None


def _section(sid, body):
    return struct.pack("<BI", sid, len(body)) + body


def to_bytes(p):
    consts = struct.pack("<H", len(p.consts))
    for s in p.consts:
        b = s.encode("utf-8")
        consts += struct.pack("<I", len(b)) + b
    funcs = struct.pack("<H", len(p.funcs))
    for f in p.funcs:
        funcs += struct.pack("<IHH", f.entry, f.nargs, f.nlocals)
    secs = [_section(S_CONST, consts), _section(S_FUNC, funcs), _section(S_CODE, p.code)]
    flags = 0
    if p.debug is not None:
        d = p.debug
        fb = d.file.encode("utf-8")
        body = struct.pack("<H", len(fb)) + fb + struct.pack("<H", len(d.names))
        for n in d.names:
            nb = n.encode("utf-8")
            body += struct.pack("<H", len(nb)) + nb
        body += struct.pack("<I", len(d.lines))
        for pc, line in d.lines:
            body += struct.pack("<II", pc, line)
        secs.append(_section(S_DEBUG, body))
        flags |= FLAG_DEBUG
    out = MAGIC + struct.pack("<HHIH", VERSION, flags, p.entry, len(secs)) + b"".join(secs)
    return out + struct.pack("<I", crc32(out))


class _R:
    def __init__(self, data):
        self.d, self.p = data, 0

    def take(self, fmt):
        size = struct.calcsize(fmt)
        if self.p + size > len(self.d):
            raise FormatError("file is truncated")
        v = struct.unpack_from(fmt, self.d, self.p)
        self.p += size
        return v if len(v) > 1 else v[0]

    def bytes(self, n):
        if self.p + n > len(self.d):
            raise FormatError("file is truncated")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b


def from_bytes(data):
    if len(data) < 18 or data[:4] != MAGIC:
        raise FormatError("not a CAT bytecode file (bad magic)")
    if struct.unpack_from("<I", data, len(data) - 4)[0] != crc32(data[:-4]):
        raise FormatError("checksum mismatch: file is corrupted or modified")
    r = _R(data[:-4])
    r.p = 4
    version, flags, entry, nsec = r.take("<HHIH")
    if version != VERSION:
        raise FormatError(f"unsupported bytecode version {version}")
    secs = {}
    for _ in range(nsec):
        sid, ln = r.take("<BI")
        if sid in secs:
            raise FormatError(f"duplicate section {sid}")
        secs[sid] = r.bytes(ln)
    for need in (S_CONST, S_FUNC, S_CODE):
        if need not in secs:
            raise FormatError(f"missing section {need}")
    try:
        c = _R(secs[S_CONST])
        consts = [c.bytes(c.take("<I")).decode("utf-8") for _ in range(c.take("<H"))]
        f = _R(secs[S_FUNC])
        funcs = [FuncInfo(*f.take("<IHH")) for _ in range(f.take("<H"))]
        debug = None
        if S_DEBUG in secs:
            d = _R(secs[S_DEBUG])
            file = d.bytes(d.take("<H")).decode("utf-8")
            names = [d.bytes(d.take("<H")).decode("utf-8") for _ in range(d.take("<H"))]
            lines = [tuple(d.take("<II")) for _ in range(d.take("<I"))]
            debug = Debug(file, names, lines)
    except UnicodeDecodeError:
        raise FormatError("bad text encoding in file")
    prog = Program(consts, funcs, secs[S_CODE], entry, debug)
    verify(prog)
    return prog


def verify(p):
    """Проверка программы ДО запуска: защита от битых и злонамеренных файлов."""
    try:
        ins = decode(p.code)
    except DecodeError as e:
        raise FormatError(str(e))
    starts = {a for a, *_ in ins}
    if not p.funcs or not 0 <= p.entry < len(p.funcs):
        raise FormatError("bad entry function")
    entries = sorted(f.entry for f in p.funcs)
    if len(set(entries)) != len(entries):
        raise FormatError("two functions share one entry point")
    for fi in p.funcs:
        if fi.entry not in starts:
            raise FormatError("function entry is not an instruction boundary")
        if fi.nargs > fi.nlocals:
            raise FormatError("function has more arguments than locals")
    if p.funcs[p.entry].nargs != 0:
        raise FormatError("entry function must take no arguments")
    bounds = entries + [len(p.code)]
    owner = {}  # адрес -> (начало, конец, nlocals)
    by_entry = {f.entry: f for f in p.funcs}
    for lo, hi in zip(bounds, bounds[1:]):
        for a, *_ in ins:
            if lo <= a < hi:
                owner[a] = (lo, hi, by_entry[lo].nlocals)
    for a, name, arg, ty in ins:
        if a not in owner:
            raise FormatError(f"code at 0x{a:04X} does not belong to any function")
        lo, hi, nl = owner[a]
        if name in JUMPS and not (lo <= arg < hi and arg in starts):
            raise FormatError(f"bad jump target 0x{arg:04X} at 0x{a:04X}")
        if name in ("LOAD", "STORE") and arg >= nl:
            raise FormatError(f"bad local slot {arg} at 0x{a:04X}")
        if name == "CALL" and arg >= len(p.funcs):
            raise FormatError(f"bad function index {arg} at 0x{a:04X}")
        if name == "PRINTS" and arg >= len(p.consts):
            raise FormatError(f"bad constant index {arg} at 0x{a:04X}")
    last = {}
    for a, name, *_ in ins:
        last[owner[a][0]] = name
    for lo, name in last.items():
        if name not in TERMINATORS:
            raise FormatError("function does not end with RET/RETV/JMP/HALT")
