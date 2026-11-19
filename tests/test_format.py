import unittest

from catlang.compiler.driver import compile_source
from catlang.vm import format as F
from catlang.vm.disasm import disassemble
from catlang.vm.vm import VM

SRC = 'fn sq(x: u32) -> u32 { return x * x; }\nfn main() { print("a"); print(sq(12)); }'


def run_prog(p):
    out = []
    VM(p, out=out.append).run()
    return "".join(out)


class Format(unittest.TestCase):
    def test_roundtrip(self):
        p = compile_source(SRC, "t.cat")
        q = F.from_bytes(F.to_bytes(p))
        self.assertEqual(run_prog(q), "a\n144\n")
        self.assertEqual(q.debug.names, ["main", "sq"])

    def test_strip_removes_debug(self):
        full = F.to_bytes(compile_source(SRC, "t.cat"))
        stripped = F.to_bytes(compile_source(SRC, "t.cat", strip=True))
        self.assertLess(len(stripped), len(full))
        self.assertIsNone(F.from_bytes(stripped).debug)
        self.assertNotIn(b"sq", stripped)
        self.assertEqual(run_prog(F.from_bytes(stripped)), "a\n144\n")

    def test_corruption_detected(self):
        data = bytearray(F.to_bytes(compile_source(SRC, "t.cat")))
        data[30] ^= 0xFF
        with self.assertRaises(F.FormatError):
            F.from_bytes(bytes(data))

    def test_bad_magic_and_truncation(self):
        data = F.to_bytes(compile_source(SRC, "t.cat"))
        for bad in (b"XXXX" + data[4:], data[:20], b"", b"CATB"):
            with self.assertRaises(F.FormatError):
                F.from_bytes(bad)

    def test_verifier_rejects_bad_jump(self):
        p = compile_source("fn main() { while true { } }", "t.cat", optimize_code=False)
        code = bytearray(p.code)
        i = code.index(0x60)  # JMP
        code[i + 1:i + 5] = (9999).to_bytes(4, "little")
        p.code = bytes(code)
        with self.assertRaises(F.FormatError):
            F.verify(p)

    def test_verifier_rejects_bad_slot(self):
        p = compile_source("fn main() { let a = 1; }", "t.cat")
        code = bytearray(p.code)
        i = code.index(0x11)  # STORE
        code[i + 1] = 50
        p.code = bytes(code)
        with self.assertRaises(F.FormatError):
            F.verify(p)

    def test_disassemble(self):
        text = disassemble(compile_source(SRC, "t.cat"))
        for word in ("main:", "sq:", "CALL", "MUL", "u32", "PRINTS"):
            self.assertIn(word, text)

    def test_dead_functions_dropped(self):
        p = compile_source("fn unused() { } fn main() { }", "t.cat")
        self.assertEqual(len(p.funcs), 1)


if __name__ == "__main__":
    unittest.main()
