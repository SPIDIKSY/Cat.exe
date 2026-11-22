"""Маленький ассемблер x86-64: только команды, нужные генератору кода CAT. Всё кодируется вручную."""
import struct

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, R15 = range(8, 16)

# коды условий (для jcc / setcc)
E, NE, B, AE, BE, A, L, GE, LE, G = 4, 5, 2, 3, 6, 7, 0xC, 0xD, 0xE, 0xF


def i32(n):
    return struct.pack("<i", n)


class Asm:
    """Буфер кода + метки + ссылки на внешние адреса (разрешает писатель формата файла)."""

    def __init__(self):
        self.buf = bytearray()
        self.labels = {}   # имя -> смещение
        self.fixups = []   # (смещение rel32, имя метки)
        self.externs = []  # (смещение rel32, символ): rip-относительная ссылка наружу (bss, iat:...)

    # --- служебное ---
    def here(self):
        return len(self.buf)

    def label(self, name):
        assert name not in self.labels, name
        self.labels[name] = len(self.buf)

    def raw(self, *bs):
        self.buf += bytes(bs)

    def data(self, b):
        self.buf += b

    def _rel(self, name):
        self.fixups.append((len(self.buf), name))
        self.buf += b"\0\0\0\0"

    def resolve(self):
        for off, name in self.fixups:
            self.buf[off:off + 4] = i32(self.labels[name] - (off + 4))

    def _rex(self, w, reg=0, rm=0, x=0, force=False):
        r = 0x40 | (w << 3) | ((reg >> 3) << 2) | ((x >> 3) << 1) | (rm >> 3)
        if r != 0x40 or force:
            self.buf.append(r)

    # --- mov ---
    def mov_rr(self, dst, src):          # mov dst, src (64)
        self._rex(1, src, dst)
        self.raw(0x89, 0xC0 | (src & 7) << 3 | (dst & 7))

    def mov_ri(self, r, v):              # mov r, imm — самая короткая форма
        v &= 0xFFFFFFFFFFFFFFFF
        if v < (1 << 32):
            self._rex(0, 0, r)
            self.raw(0xB8 + (r & 7))
            self.buf += struct.pack("<I", v)
        elif v >= (1 << 64) - (1 << 31):
            self._rex(1, 0, r)
            self.raw(0xC7, 0xC0 | (r & 7))
            self.buf += struct.pack("<I", v & 0xFFFFFFFF)
        else:
            self._rex(1, 0, r)
            self.raw(0xB8 + (r & 7))
            self.buf += struct.pack("<Q", v)

    def load_rbp(self, r, disp):         # mov r, [rbp+disp]
        self._rex(1, r, RBP)
        self.raw(0x8B, 0x85 | (r & 7) << 3)
        self.buf += i32(disp)

    def store_rbp(self, disp, r):        # mov [rbp+disp], r
        self._rex(1, r, RBP)
        self.raw(0x89, 0x85 | (r & 7) << 3)
        self.buf += i32(disp)

    def _mem_r15_rax(self, opcode, reg, w=0, prefix=None, two=False):
        """Команда с операндом памяти [r15 + rax] (SIB)."""
        if prefix:
            self.buf.append(prefix)
        self._rex(w, reg, R15, RAX, force=(reg >= 4 and not w and opcode in (0x88,)))
        if two:
            self.buf.append(0x0F)
        self.raw(opcode, 0x04 | (reg & 7) << 3, 0x07)  # mod=00 rm=100(SIB), SIB: scale=0 index=rax base=r15

    def load_mem(self, bits):            # rax = zero-extended [r15+rax]
        if bits == 8:
            self._mem_r15_rax(0xB6, RAX, two=True)
        elif bits == 16:
            self._mem_r15_rax(0xB7, RAX, two=True)
        elif bits == 32:
            self._mem_r15_rax(0x8B, RAX)
        else:
            self._mem_r15_rax(0x8B, RAX, w=1)

    def store_mem(self, bits):           # [r15+rax] = rcx (младшие bits)
        if bits == 8:
            self._mem_r15_rax(0x88, RCX)
        elif bits == 16:
            self._mem_r15_rax(0x89, RCX, prefix=0x66)
        elif bits == 32:
            self._mem_r15_rax(0x89, RCX)
        else:
            self._mem_r15_rax(0x89, RCX, w=1)

    # --- арифметика ---
    def alu_rr(self, op, dst, src):      # op in add/sub/and/or/xor/cmp/test
        code = {"add": 0x01, "or": 0x09, "and": 0x21, "sub": 0x29, "xor": 0x31, "cmp": 0x39, "test": 0x85}[op]
        self._rex(1, src, dst)
        self.raw(code, 0xC0 | (src & 7) << 3 | (dst & 7))

    def imul_rr(self, dst, src):
        self._rex(1, dst, src)
        self.raw(0x0F, 0xAF, 0xC0 | (dst & 7) << 3 | (src & 7))

    def alu_ri(self, op, r, imm):        # add/sub/cmp r, imm32
        ext = {"add": 0, "sub": 5, "cmp": 7, "and": 4}[op]
        self._rex(1, 0, r)
        self.raw(0x81, 0xC0 | ext << 3 | (r & 7))
        self.buf += i32(imm)

    def unary(self, op, r):              # neg/not/idiv/div  (64)
        ext = {"not": 2, "neg": 3, "div": 6, "idiv": 7}[op]
        self._rex(1, 0, r)
        self.raw(0xF7, 0xC0 | ext << 3 | (r & 7))

    def cqo(self):
        self.raw(0x48, 0x99)

    def shift_cl(self, op, r):           # shl/shr/sar r, cl
        ext = {"shl": 4, "shr": 5, "sar": 7}[op]
        self._rex(1, 0, r)
        self.raw(0xD3, 0xC0 | ext << 3 | (r & 7))

    def shl_imm(self, r, n):
        self._rex(1, 0, r)
        self.raw(0xC1, 0xE0 | (r & 7), n)

    def xor_eax_imm1(self):              # xor eax, 1
        self.raw(0x83, 0xF0, 0x01)

    def test_eax(self):
        self.raw(0x85, 0xC0)

    def setcc(self, cc):                 # al = cc ? 1 : 0 ; затем movzx eax, al
        self.raw(0x0F, 0x90 + cc, 0xC0)
        self.raw(0x0F, 0xB6, 0xC0)

    # расширение rax до значения типа: bits 8/16/32, signed
    def extend(self, bits, signed):
        if bits == 8:
            self.raw(0x48, 0x0F, 0xBE, 0xC0) if signed else self.raw(0x0F, 0xB6, 0xC0)
        elif bits == 16:
            self.raw(0x48, 0x0F, 0xBF, 0xC0) if signed else self.raw(0x0F, 0xB7, 0xC0)
        elif bits == 32:
            self.raw(0x48, 0x63, 0xC0) if signed else self.raw(0x89, 0xC0)

    # --- стек, переходы, вызовы ---
    def push(self, r):
        self._rex(0, 0, r)
        self.raw(0x50 + (r & 7))

    def pop(self, r):
        self._rex(0, 0, r)
        self.raw(0x58 + (r & 7))

    def jmp(self, name):
        self.raw(0xE9)
        self._rel(name)

    def jcc(self, cc, name):
        self.raw(0x0F, 0x80 + cc)
        self._rel(name)

    def call(self, name):
        self.raw(0xE8)
        self._rel(name)

    def ret(self):
        self.raw(0xC3)

    def leave(self):
        self.raw(0xC9)

    def lea_label(self, r, name):        # lea r, [rip+метка]
        self._rex(1, r, 0)
        self.raw(0x8D, 0x05 | (r & 7) << 3)
        self._rel(name)

    def lea_extern(self, r, sym):        # lea r, [rip+внешний_символ]
        self._rex(1, r, 0)
        self.raw(0x8D, 0x05 | (r & 7) << 3)
        self.externs.append((len(self.buf), sym))
        self.buf += b"\0\0\0\0"

    def call_extern(self, sym):          # call [rip+внешний_символ] (например, ячейка IAT)
        self.raw(0xFF, 0x15)
        self.externs.append((len(self.buf), sym))
        self.buf += b"\0\0\0\0"

    def test_eax_rax(self):              # test rax, rax
        self.raw(0x48, 0x85, 0xC0)

    def store_r15(self, disp, r):        # mov [r15+disp32], r
        self._rex(1, r, R15)
        self.raw(0x89, 0x87 | (r & 7) << 3)
        self.buf += i32(disp)

    def syscall(self):
        self.raw(0x0F, 0x05)

    def rdtsc(self):
        self.raw(0x0F, 0x31)
