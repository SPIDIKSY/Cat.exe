"""Загрузчик-эмулятор для проверки PE (Windows) и Mach-O (macOS Intel) без настоящих систем.

Берёт готовый файл, читает его ЧУЖИМИ разборщиками (pefile, macholib), раскладывает сегменты в память эмулятора
процессора (unicorn) по таблицам самого файла и запускает с точки входа. Вызовы Windows API и системные вызовы
macOS подменяются заглушками. Нужны пакеты: unicorn pefile macholib (только для тестов; не зависимости CAT).
"""
import struct
import tempfile

try:
    import pefile
    from macholib.MachO import MachO
    from unicorn import (UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_INSN, UC_MODE_64, UC_PROT_ALL, UC_PROT_EXEC,
                         UC_PROT_READ, UC_PROT_WRITE, Uc, UcError)
    from unicorn.x86_const import (UC_X86_INS_SYSCALL, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_RAX,
                                   UC_X86_REG_RCX, UC_X86_REG_RDI, UC_X86_REG_RDX, UC_X86_REG_RIP,
                                   UC_X86_REG_RSI, UC_X86_REG_RSP)
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

PAGE = 0x1000
STACK_TOP = 0x7FF00000 + 0x200000
FAKE_API = 0x70000000
MAX_STEPS = 400_000_000


def _up(n):
    return (n + PAGE - 1) // PAGE * PAGE


class Run:
    def __init__(self, stdin):
        self.stdin, self.out, self.err, self.code, self.problems = bytearray(stdin), bytearray(), bytearray(), None, []

    def write(self, fd, data):
        (self.out if fd == 1 else self.err).extend(data)

    def read(self, n):
        chunk, self.stdin = self.stdin[:n], self.stdin[n:]
        return bytes(chunk)


def _finish(uc, run, entry):
    try:
        uc.emu_start(entry, 0xFFFFFFFFFFFF, 0, MAX_STEPS)
    except UcError as e:
        run.problems.append(f"emulator error: {e} at rip=0x{uc.reg_read(UC_X86_REG_RIP):x}")
    if run.code is None:
        run.problems.append("program neither exited nor crashed (step limit?)")
    return run.out.decode("utf-8"), run.code, run.err.decode("utf-8"), run.problems


def run_pe(data, stdin=b""):
    pe = pefile.PE(data=data, fast_load=False)
    warnings = [w for w in pe.get_warnings() if "makes up" not in w]  # эвристика про нулевые байты — не про структуру
    assert not warnings, warnings
    assert pe.NT_HEADERS.Signature == 0x4550 and pe.OPTIONAL_HEADER.Magic == 0x20B
    uc, run = Uc(UC_ARCH_X86, UC_MODE_64), Run(stdin)
    base = pe.OPTIONAL_HEADER.ImageBase
    uc.mem_map(base, _up(pe.OPTIONAL_HEADER.SizeOfHeaders))
    uc.mem_write(base, data[:pe.OPTIONAL_HEADER.SizeOfHeaders])
    for s in pe.sections:  # как загрузчик: виртуальный адрес, размер, права из заголовка секции
        size = _up(max(s.Misc_VirtualSize, s.SizeOfRawData))
        uc.mem_map(base + s.VirtualAddress, size, UC_PROT_ALL)
        uc.mem_write(base + s.VirtualAddress, s.get_data()[:s.SizeOfRawData])
    assert pe.OPTIONAL_HEADER.SizeOfImage >= max(s.VirtualAddress + s.Misc_VirtualSize for s in pe.sections)
    uc.mem_map(FAKE_API, PAGE, UC_PROT_ALL)
    apis = {}
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        assert entry.dll.lower() == b"kernel32.dll"
        for i, imp in enumerate(entry.imports):
            fake = FAKE_API + 16 * len(apis)
            apis[fake] = imp.name.decode()
            uc.mem_write(imp.address, struct.pack("<Q", fake))   # загрузчик заполняет IAT
    uc.mem_map(STACK_TOP - 0x200000, 0x200000, UC_PROT_READ | UC_PROT_WRITE)
    uc.reg_write(UC_X86_REG_RSP, STACK_TOP - 0x108)             # как при входе: rsp ≡ 8 (mod 16)

    def api(uc, address, size, _):
        name = apis[address]
        rsp = uc.reg_read(UC_X86_REG_RSP)
        if rsp % 16 != 8:  # ABI Windows: на входе в функцию rsp ≡ 8 (mod 16)
            run.problems.append(f"{name}: stack is not 16-byte aligned at the call (rsp=0x{rsp:x})")
        a = [uc.reg_read(r) for r in (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9)]
        ret = 1
        if name == "GetStdHandle":
            ret = {0xFFFFFFF6: 10, 0xFFFFFFF5: 11, 0xFFFFFFF4: 12}.get(a[0] & 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
        elif name in ("WriteFile", "ReadFile"):
            if (struct.unpack("<Q", uc.mem_read(rsp + 0x28, 8))[0]) != 0:
                run.problems.append(f"{name}: lpOverlapped must be NULL")
            if name == "WriteFile":
                run.write(1 if a[0] == 11 else 2, bytes(uc.mem_read(a[1], a[2])))
                n = a[2]
            else:
                assert a[0] == 10
                chunk = run.read(a[2])
                uc.mem_write(a[1], chunk)
                n = len(chunk)
            uc.mem_write(a[3], struct.pack("<I", n))
        elif name == "ExitProcess":
            run.code = a[0] & 0xFFFFFFFF
            uc.emu_stop()
            return
        uc.reg_write(UC_X86_REG_RAX, ret)
        uc.reg_write(UC_X86_REG_RIP, struct.unpack("<Q", uc.mem_read(rsp, 8))[0])  # ret
        uc.reg_write(UC_X86_REG_RSP, rsp + 8)

    uc.hook_add(UC_HOOK_CODE, api, None, FAKE_API, FAKE_API + PAGE)
    return _finish(uc, run, base + pe.OPTIONAL_HEADER.AddressOfEntryPoint)


def _syscalls(uc, run, numbers):
    wr, rd, ex = numbers

    def on_syscall(uc, _):
        n = uc.reg_read(UC_X86_REG_RAX)
        a = [uc.reg_read(r) for r in (UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX)]
        if n == wr:
            run.write(a[0], bytes(uc.mem_read(a[1], a[2])))
            uc.reg_write(UC_X86_REG_RAX, a[2])
        elif n == rd:
            chunk = run.read(a[2])
            uc.mem_write(a[1], chunk)
            uc.reg_write(UC_X86_REG_RAX, len(chunk))
        elif n == ex:
            run.code = a[0] & 0xFFFFFFFF
            uc.emu_stop()
        else:
            run.problems.append(f"unexpected syscall {n:#x}")
            uc.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)


def run_macho(data, stdin=b""):
    uc, run = Uc(UC_ARCH_X86, UC_MODE_64), Run(stdin)
    with tempfile.NamedTemporaryFile(suffix=".macho") as f:
        f.write(data)
        f.flush()
        hdr = MachO(f.name).headers[0]
    assert hdr.header.cputype == 0x01000007 and hdr.header.filetype == 2
    rip = None
    for lc, cmd, rest in hdr.commands:
        if lc.cmd == 0x19:  # LC_SEGMENT_64
            name = cmd.segname.rstrip(b"\0")
            if name == b"__PAGEZERO":
                continue
            uc.mem_map(cmd.vmaddr, _up(cmd.vmsize), UC_PROT_ALL)
            uc.mem_write(cmd.vmaddr, data[cmd.fileoff:cmd.fileoff + cmd.filesize])
        elif lc.cmd == 0x5:  # LC_UNIXTHREAD
            raw = data[hdr.offset + 32:]
            off = raw.index(struct.pack("<IIII", 0x5, lc.cmdsize, 4, 42))
            regs = struct.unpack_from("<21Q", raw, off + 16)
            rip = regs[16]
    assert rip is not None
    uc.mem_map(STACK_TOP - 0x200000, 0x200000, UC_PROT_READ | UC_PROT_WRITE)
    uc.reg_write(UC_X86_REG_RSP, STACK_TOP - 0x100)
    _syscalls(uc, run, (0x2000004, 0x2000003, 0x2000001))
    return _finish(uc, run, rip)
