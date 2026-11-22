"""Системные заглушки для нативных программ: три операции (write/read/exit) для каждой ОС.

Соглашение внутри программы: аргументы в rdi, rsi, rdx; результат в rax. Только здесь код различается по ОС.
Linux и macOS (Intel) — системные вызовы ядра; Windows — функции kernel32.dll через таблицу импорта (IAT).
"""
from .asm import RAX, RBP, RCX, RDI, RDX, RSI, RSP, R8, R9

TARGETS = ("linux", "windows", "macos")
WIN_IMPORTS = ["GetStdHandle", "WriteFile", "ReadFile", "ExitProcess", "SetConsoleOutputCP", "SetConsoleCP"]
SYSCALLS = {  # (write, read, exit)
    "linux": (1, 0, 60),
    "macos": (0x2000004, 0x2000003, 0x2000001),
}
TRAP_MESSAGES = {
    1: "division by zero", 2: "shift amount is out of range", 3: "assertion failed",
    4: "memory access out of bounds", 5: "rand(0): range is empty", 6: "end of input",
}


def lea_rbp(a, r, disp):
    a._rex(1, r, 0)
    a.raw(0x8D, 0x85 | (r & 7) << 3)
    a.data(disp.to_bytes(4, "little", signed=True))


def emit_stubs(a, target):
    """Метки os_write, os_read, os_exit, os_trap."""
    if target in SYSCALLS:
        for name, num in zip(("os_write", "os_read", "os_exit"), SYSCALLS[target]):
            a.label(name)
            a.mov_ri(RAX, num)
            a.syscall()
            a.ret()
    else:
        for name, api in (("os_write", "WriteFile"), ("os_read", "ReadFile")):
            a.label(name)
            a.push(RBP)
            a.mov_rr(RBP, RSP)
            a.alu_ri("sub", RSP, 64)
            a.alu_ri("and", RSP, -16)
            a.store_rbp(-8, RSI)
            a.store_rbp(-16, RDX)
            a.mov_ri(RAX, 0)
            a.store_rbp(-24, RAX)
            a.mov_ri(RCX, 0xFFFFFFF6)          # -10 - fd: 0 -> stdin, 1 -> stdout, 2 -> stderr
            a.raw(0x29, 0xF9)                  # sub ecx, edi
            a.call_extern("iat:GetStdHandle")
            a.mov_rr(RCX, RAX)
            a.load_rbp(RDX, -8)
            a.load_rbp(R8, -16)
            lea_rbp(a, R9, -24)
            a.raw(0x48, 0xC7, 0x44, 0x24, 0x20, 0, 0, 0, 0)  # mov qword [rsp+32], 0
            a.call_extern("iat:" + api)
            a.raw(0x8B, 0x45, 0xE8)            # mov eax, [rbp-24]  (сколько байт обработано)
            a.leave()
            a.ret()
        a.label("os_exit")
        a.mov_rr(RCX, RDI)
        a.alu_ri("and", RSP, -16)
        a.alu_ri("sub", RSP, 32)
        a.call_extern("iat:ExitProcess")
    # ловушка: rdi = номер; печатает сообщение в stderr и завершает программу с кодом 3
    a.label("os_trap")
    for k, msg in TRAP_MESSAGES.items():
        a.alu_ri("cmp", RDI, k)
        a.jcc(4, f".trapmsg{k}")
    for k, msg in TRAP_MESSAGES.items():
        a.label(f".trapmsg{k}")
        a.lea_label(RSI, f".trapstr{k}")
        a.mov_ri(RDX, len(f"runtime error: {msg}\n".encode()))
        a.jmp(".trapout")
    a.label(".trapout")
    a.mov_ri(RDI, 2)
    a.call("os_write")
    a.mov_ri(RDI, 3)
    a.call("os_exit")
    for k, msg in TRAP_MESSAGES.items():
        a.label(f".trapstr{k}")
        a.data(f"runtime error: {msg}\n".encode())
