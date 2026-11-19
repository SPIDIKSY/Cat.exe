"""Виртуальная машина CAT (стековая). Модель исполнения — docs/DESIGN.md."""
from ..core.alu import FastALU
from ..core.cattypes import BY_CODE, U32, wrap
from .format import verify
from .opcodes import decode

MAX_FRAMES = 10_000
MAX_STACK = 1_000_000
USER_MEM = 65536          # peek*/poke* (look*/bat*) работают только здесь
HEAP_START = USER_MEM     # дальше — куча (массивы и строки)
MEM_SIZE = 4 * 1024 * 1024


def _parse_int(text):
    """'  -42 ' -> -42; всё остальное -> None."""
    t = text.strip()
    body = t[1:] if t[:1] in ("+", "-") else t
    return int(t) if body.isdigit() and body.isascii() else None


class CatTrap(Exception):
    """Ошибка времени выполнения (ловушка)."""

    def __init__(self, message, where=""):
        super().__init__(message)
        self.message, self.where = message, where


class VM:
    def __init__(self, program, alu=None, out=None, max_steps=None, inp=None, seed=None):
        verify(program)
        self.p = program
        self.alu = alu or FastALU()
        self.out = out or (lambda s: None)
        self.max_steps = max_steps
        self.inp = inp or (lambda: None)
        self.rng = (seed or 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF or 1
        self.in_ok = True
        self.mem = bytearray(MEM_SIZE)
        self.top = HEAP_START
        self.const_h = [self.new_str(c.encode("utf-8")) for c in program.consts]
        ins = decode(program.code)
        self.addr2ix = {a: i for i, (a, *_) in enumerate(ins)}
        self.ins = []
        for a, name, arg, ty in ins:
            if name in ("JMP", "JZ", "JNZ"):
                arg = self.addr2ix[arg]
            self.ins.append((name, arg, BY_CODE.get(ty)))

    # --- куча: простой «бампер»-аллокатор без освобождения ---
    def alloc(self, nbytes):
        size = (nbytes + 7) & ~7
        if self.top + size > MEM_SIZE:
            raise CatTrap("out of memory")
        h, self.top = self.top, self.top + size
        return h

    def new_str(self, data):
        h = self.alloc(4 + len(data))
        self.mem[h:h + 4 + len(data)] = len(data).to_bytes(4, "little") + data
        return h

    def length(self, h):
        """Длина массива/строки; проверяет, что h — настоящий объект кучи."""
        if h < HEAP_START or h + 4 > self.top:
            raise CatTrap("invalid reference (null or corrupted)")
        return int.from_bytes(self.mem[h:h + 4], "little")

    def text(self, h):
        n = self.length(h)
        return bytes(self.mem[h + 4:h + 4 + n])

    def elem_addr(self, h, i, es):
        n = self.length(h)
        if not 0 <= i < n or h + 4 + n * es > self.top:
            raise CatTrap(f"index {i} is out of bounds (length {n})")
        return h + 4 + i * es

    # --- место ошибки ---
    def where(self, ip, fn):
        d = self.p.debug
        name = d.names[fn] if d and fn < len(d.names) else f"fn#{fn}"
        addr = list(self.addr2ix)[ip] if 0 <= ip < len(self.ins) else -1
        line = None
        if d:
            for pc, ln in d.lines:
                if pc > addr:
                    break
                line = ln
        return f"in function '{name}'" + (f", line {line}" if line else f", pc 0x{max(addr, 0):04X}")

    def run(self):
        """Выполняет программу, возвращает код выхода (значение main или 0)."""
        p, alu, ins = self.p, self.alu, self.ins
        funcs = p.funcs
        entry_ix = self.addr2ix[funcs[p.entry].entry]
        stack, frames = [], []
        fn = p.entry
        loc = [0] * funcs[fn].nlocals
        ip, steps, limit = entry_ix, 0, self.max_steps
        push, pop = stack.append, stack.pop
        mem, out = self.mem, self.out
        try:
            while True:
                if limit is not None:
                    steps += 1
                    if steps > limit:
                        raise CatTrap("step limit exceeded")
                if ip >= len(ins):
                    raise CatTrap("execution ran past the end of code")
                op, arg, ty = ins[ip]
                ip += 1
                if op == "LOAD":
                    push(loc[arg])
                elif op == "PUSH":
                    push(arg)
                elif op == "STORE":
                    loc[arg] = pop()
                elif op == "ADD":
                    b = pop(); push(alu.add(pop(), b, ty))
                elif op == "SUB":
                    b = pop(); push(alu.sub(pop(), b, ty))
                elif op == "MUL":
                    b = pop(); push(alu.mul(pop(), b, ty))
                elif op == "JZ":
                    if not pop():
                        ip = arg
                elif op == "JMP":
                    ip = arg
                elif op == "JNZ":
                    if pop():
                        ip = arg
                elif op in ("EQ", "NE", "LT", "LE", "GT", "GE", "CAT", "CATS", "PAW"):
                    b = pop(); push(getattr(alu, op.lower())(pop(), b, ty))
                elif op in ("DIV", "REM"):
                    b = pop()
                    if b == 0:
                        raise CatTrap("division by zero")
                    push(getattr(alu, op.lower())(pop(), b, ty))
                elif op in ("SHL", "SHR"):
                    b = pop()
                    if not 0 <= b < ty.bits:
                        raise CatTrap(f"shift amount {b} is out of range for {ty}")
                    push(getattr(alu, op.lower())(pop(), b, ty))
                elif op == "MEOW":
                    push(alu.meow(pop(), ty))
                elif op == "NEG":
                    push(alu.neg(pop(), ty))
                elif op == "CAST":
                    push(alu.cast(pop(), ty))
                elif op == "POP":
                    pop()
                elif op == "DUP":
                    push(stack[-1])
                elif op == "CALL":
                    if len(frames) >= MAX_FRAMES:
                        raise CatTrap("call stack overflow (too deep recursion)")
                    f = funcs[arg]
                    new = [0] * f.nlocals
                    for i in range(f.nargs - 1, -1, -1):
                        new[i] = pop()
                    frames.append((ip, loc, fn))
                    ip, loc, fn = self.addr2ix[f.entry], new, arg
                elif op == "RET" or op == "RETV":
                    val = pop() if op == "RET" else None
                    if not frames:
                        return (val or 0) & 0xFF
                    ip, loc, fn = frames.pop()
                    if val is not None:
                        push(val)
                elif op == "PRINTI":
                    out(f"{pop()}\n")
                elif op == "PRINTB":
                    out("true\n" if pop() else "false\n")
                elif op == "PRINTS":
                    out(p.consts[arg] + "\n")
                elif op == "WRITEI":
                    out(str(pop()))
                elif op == "WRITEB":
                    out("true" if pop() else "false")
                elif op == "WRITES":
                    out(p.consts[arg])
                elif op == "READI":
                    line = self.inp()
                    if line is None:
                        raise CatTrap("end of input")
                    v = _parse_int(line)
                    self.in_ok = v is not None and -(1 << 63) <= v < (1 << 63)
                    push(v if self.in_ok else 0)
                elif op == "INOK":
                    push(int(self.in_ok))
                elif op == "RAND":
                    n = pop()
                    if n == 0:
                        raise CatTrap("rand(0): range is empty")
                    x = self.rng  # xorshift64: только сдвиги и PAW
                    x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF
                    x ^= x >> 7
                    x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
                    self.rng = x
                    push(x % n)
                elif op == "LOADM":
                    a = pop()
                    n = ty.bits // 8
                    if a + n > USER_MEM:
                        raise CatTrap(f"memory read out of bounds (address {a})")
                    push(wrap(int.from_bytes(mem[a:a + n], "little"), ty))
                elif op == "STOREM":
                    v = pop()
                    a = pop()
                    n = ty.bits // 8
                    if a + n > USER_MEM:
                        raise CatTrap(f"memory write out of bounds (address {a})")
                    mem[a:a + n] = (v & ty.mask).to_bytes(n, "little")
                elif op == "ALOAD":
                    i = pop()
                    es = max(1, ty.bits // 8)
                    a = self.elem_addr(pop(), i, es)
                    push(wrap(int.from_bytes(mem[a:a + es], "little"), ty))
                elif op == "ASTORE":
                    v = pop()
                    i = pop()
                    es = max(1, ty.bits // 8)
                    a = self.elem_addr(pop(), i, es)
                    mem[a:a + es] = (v & ty.mask).to_bytes(es, "little")
                elif op == "NEWARR":
                    n = pop()
                    v = pop()
                    es = max(1, ty.bits // 8)
                    if n * es > MEM_SIZE - self.top:
                        raise CatTrap("out of memory")
                    h = self.alloc(4 + n * es)
                    mem[h:h + 4 + n * es] = n.to_bytes(4, "little") + (v & ty.mask).to_bytes(es, "little") * n
                    push(h)
                elif op == "ALEN":
                    push(self.length(pop()))
                elif op == "STR":
                    push(self.const_h[arg])
                elif op == "SCAT":
                    b = self.text(pop())
                    push(self.new_str(self.text(pop()) + b))
                elif op == "STREQ":
                    b = self.text(pop())
                    push(int(self.text(pop()) == b))
                elif op == "ITOS":
                    push(self.new_str(str(pop()).encode("ascii")))
                elif op == "READS":
                    line = self.inp()
                    if line is None:
                        raise CatTrap("end of input")
                    push(self.new_str(line.encode("utf-8")))
                elif op == "PRINTV":
                    out(self.text(pop()).decode("utf-8", "replace") + "\n")
                elif op == "WRITEV":
                    out(self.text(pop()).decode("utf-8", "replace"))
                elif op == "ASSERT":
                    if not pop():
                        raise CatTrap("assertion failed")
                elif op == "HALT":
                    return 0
                else:
                    raise CatTrap(f"unimplemented instruction {op}")
                if len(stack) > MAX_STACK:
                    raise CatTrap("value stack overflow")
        except CatTrap as e:
            e.where = self.where(ip - 1, fn)
            raise
        except IndexError:
            raise CatTrap("value stack underflow", self.where(ip - 1, fn))
