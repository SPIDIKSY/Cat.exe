"""Писатели исполняемых файлов: ELF64 (Linux), PE32+ (Windows), Mach-O x86-64 (macOS, Intel).

Все три — простые статические файлы без внешних утилит: код + (только Windows) таблица импорта kernel32.dll
+ нулевая область памяти (bss) для пользовательской памяти программы.
"""
import struct

from .codegen import BSS_SIZE
from .platform import WIN_IMPORTS


def _link(a, code_addr, symbols):
    """Разрешить rip-относительные ссылки наружу: symbols — адреса (символ -> абсолютный адрес)."""
    code = bytearray(a.buf)
    for off, sym in a.externs:
        rel = symbols[sym] - (code_addr + off + 4)
        code[off:off + 4] = struct.pack("<i", rel)
    return bytes(code)


def _align(n, k):
    return (n + k - 1) // k * k


# ---------------------------------------------------------------- ELF64 (Linux)
def make_elf(a):
    base, bss, code_off = 0x400000, 0x10000000, 0x100
    code = _link(a, base + code_off, {"bss": bss})
    total = code_off + len(code)
    entry = base + code_off + a.labels["_start"]
    ehdr = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9, 2, 0x3E, 1, entry, 64, 0, 0,
                       64, 56, 2, 64, 0, 0)
    ph1 = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, total, total, 0x1000)
    ph2 = struct.pack("<IIQQQQQQ", 1, 6, 0, bss, bss, 0, BSS_SIZE, 0x1000)
    return (ehdr + ph1 + ph2).ljust(code_off, b"\0") + code


# ---------------------------------------------------------------- PE32+ (Windows)
IMAGE_BASE = 0x140000000


def make_pe(a):
    file_align, sec_align = 0x200, 0x1000
    text_rva = 0x1000
    code_len = len(a.buf)
    idata_rva = text_rva + _align(code_len, sec_align)
    # --- секция импорта ---
    dll = b"kernel32.dll\0"
    n = len(WIN_IMPORTS)
    idt_size = 20 * 2                       # дескриптор kernel32 + нулевой
    ilt_off = idt_size
    iat_off = ilt_off + 8 * (n + 1)
    names_off = iat_off + 8 * (n + 1)
    hint_names, name_rvas, pos = b"", [], names_off
    for nm in WIN_IMPORTS:
        entry = struct.pack("<H", 0) + nm.encode() + b"\0"
        if len(entry) % 2:
            entry += b"\0"
        name_rvas.append(idata_rva + pos)
        hint_names += entry
        pos += len(entry)
    dll_off = pos
    idata = bytearray(idt_size)
    struct.pack_into("<IIIII", idata, 0, idata_rva + ilt_off, 0, 0, idata_rva + dll_off, idata_rva + iat_off)
    ilt = b"".join(struct.pack("<Q", r) for r in name_rvas) + b"\0" * 8
    idata += ilt + ilt + hint_names + dll
    bss_rva = idata_rva + _align(len(idata), sec_align)
    symbols = {"bss": IMAGE_BASE + bss_rva}
    for i, nm in enumerate(WIN_IMPORTS):
        symbols["iat:" + nm] = IMAGE_BASE + idata_rva + iat_off + 8 * i
    code = _link(a, IMAGE_BASE + text_rva, symbols)
    text_raw, idata_raw = _align(len(code), file_align), _align(len(idata), file_align)
    headers_size = 0x400
    text_ptr, idata_ptr = headers_size, headers_size + text_raw
    image_size = bss_rva + _align(BSS_SIZE, sec_align)
    dos = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x80)
    dos = dos.ljust(0x80, b"\0")
    coff = struct.pack("<HHIIIHH", 0x8664, 3, 0, 0, 0, 240, 0x0022)  # EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE
    entry_rva = text_rva + a.labels["_start"]
    opt = struct.pack("<HBBIIIIIQIIHHHHHHIIIIHHQQQQII", 0x20B, 14, 0, text_raw, idata_raw, 0, entry_rva, text_rva,
                      IMAGE_BASE, sec_align, file_align, 6, 0, 0, 0, 6, 0, 0, image_size, headers_size, 0,
                      3, 0x8100, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    dirs = [(0, 0)] * 16
    dirs[1] = (idata_rva, idt_size)                      # таблица импорта
    dirs[12] = (idata_rva + iat_off, 8 * (n + 1))        # IAT
    opt += b"".join(struct.pack("<II", *d) for d in dirs)

    def sec(name, vsize, rva, rsize, ptr, flags):
        return struct.pack("<8sIIIIIIHHI", name, vsize, rva, rsize, ptr, 0, 0, 0, 0, flags)
    secs = (sec(b".text", len(code), text_rva, text_raw, text_ptr, 0x60000020)
            + sec(b".idata", len(idata), idata_rva, idata_raw, idata_ptr, 0xC0000040)
            + sec(b".bss", BSS_SIZE, bss_rva, 0, 0, 0xC0000080))
    head = (dos + b"PE\0\0" + coff + opt + secs).ljust(headers_size, b"\0")
    return head + code.ljust(text_raw, b"\0") + bytes(idata).ljust(idata_raw, b"\0")


# ---------------------------------------------------------------- Mach-O x86-64 (macOS, Intel)
def make_macho(a):
    base, page = 0x100000000, 0x1000
    code_off = 0x400

    def seg(name, vmaddr, vmsize, fileoff, filesize, maxprot, initprot, sections=b"", nsects=0):
        return struct.pack("<II16sQQQQIIII", 0x19, 72 + len(sections), name, vmaddr, vmsize, fileoff, filesize,
                           maxprot, initprot, nsects, 0) + sections

    def section(sect, segn, addr, size, off, flags):
        return struct.pack("<16s16sQQIIIIIIII", sect, segn, addr, size, off, 4 if flags else 0, 0, 0, flags, 0, 0, 0)

    code_len = len(a.buf)
    text_size = _align(code_off + code_len, page)
    data_addr = base + text_size
    bss_size = _align(BSS_SIZE, page)
    code = _link(a, base + code_off, {"bss": data_addr})
    entry = base + code_off + a.labels["_start"]
    cmds = seg(b"__PAGEZERO", 0, base, 0, 0, 0, 0)
    cmds += seg(b"__TEXT", base, text_size, 0, text_size, 7, 5,
                section(b"__text", b"__TEXT", base + code_off, code_len, code_off, 0x80000400), 1)
    cmds += seg(b"__DATA", data_addr, bss_size, 0, 0, 3, 3,
                section(b"__bss", b"__DATA", data_addr, BSS_SIZE, 0, 0x1), 1)
    regs = [0] * 21
    regs[16] = entry  # rip
    cmds += struct.pack("<IIII", 0x5, 16 + 42 * 4, 4, 42) + struct.pack("<21Q", *regs)
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x01000007, 3, 2, 4, len(cmds), 1, 0)
    return (header + cmds).ljust(code_off, b"\0") + code + b"\0" * (text_size - code_off - code_len)


MAKERS = {"linux": make_elf, "windows": make_pe, "macos": make_macho}
