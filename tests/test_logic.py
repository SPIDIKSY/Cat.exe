import itertools
import random
import unittest
import zlib

from catlang.core import logic as L
from catlang.core.alu import FastALU, GateALU
from catlang.core.cattypes import I8, I16, I32, I64, TYPES, U8, U16, U32, U64, Type, wrap
from catlang.vm.format import crc32


class TruthTables(unittest.TestCase):
    def test_tables(self):
        for a, b in itertools.product((0, 1), repeat=2):
            self.assertEqual(L.cat(a, b), a and b)
            self.assertEqual(L.cats(a, b), a or b)
            self.assertEqual(L.paw(a, b), a ^ b)
        self.assertEqual((L.meow(0), L.meow(1)), (1, 0))

    def test_functional_completeness(self):
        # CATS и PAW выражаются через CAT и MEOW
        for a, b in itertools.product((0, 1), repeat=2):
            self.assertEqual(L.cats(a, b), L.meow(L.cat(L.meow(a), L.meow(b))))
            self.assertEqual(L.paw(a, b), L.cat(L.cats(a, b), L.meow(L.cat(a, b))))

    def test_full_adder(self):
        for a, b, c in itertools.product((0, 1), repeat=3):
            s, co = L.full_adder(a, b, c)
            self.assertEqual(s + 2 * co, a + b + c)


class Equivalence(unittest.TestCase):
    """Быстрое АЛУ == АЛУ на вентилях."""
    BIN = ["cat", "cats", "paw", "add", "sub", "mul", "div", "rem", "shl", "shr",
           "eq", "ne", "lt", "le", "gt", "ge"]

    def check(self, t, a, b):
        f, g = FastALU(), GateALU()
        for op in self.BIN:
            if op in ("div", "rem") and b == 0:
                continue
            if op in ("shl", "shr") and not 0 <= b < t.bits:
                continue
            self.assertEqual(getattr(f, op)(a, b, t), getattr(g, op)(a, b, t), (op, t, a, b))
        for op in ("meow", "neg", "cast"):
            self.assertEqual(getattr(f, op)(a, t), getattr(g, op)(a, t), (op, t, a))

    def test_exhaustive_4bit(self):
        for signed in (False, True):
            t = Type("t4", 4, signed, 99)
            vals = range(-8, 8) if signed else range(16)
            for a in vals:
                for b in vals:
                    self.check(t, a, b)

    def test_random_all_types(self):
        rnd = random.Random(1)
        for t in TYPES[1:]:
            lo, hi = (-(1 << (t.bits - 1)), (1 << (t.bits - 1)) - 1) if t.signed else (0, t.mask)
            edge = [lo, hi, 0, 1, -1 if t.signed else hi]
            for _ in range(25):
                a = rnd.choice(edge + [rnd.randint(lo, hi)])
                b = rnd.choice(edge + [rnd.randint(lo, hi), rnd.randint(0, t.bits - 1)])
                self.check(t, a, b)

    def test_signed_division_edge(self):
        f, g = FastALU(), GateALU()
        self.assertEqual(f.div(-7, 2, I8), -3)
        self.assertEqual(f.rem(-7, 2, I8), -1)
        self.assertEqual(g.div(-7, 2, I8), -3)
        self.assertEqual(g.rem(-7, 2, I8), -1)
        self.assertEqual(f.div(-128, -1, I8), g.div(-128, -1, I8))  # переполнение: оборачивается


class Crc(unittest.TestCase):
    def test_crc32(self):
        for d in (b"", b"CAT", bytes(range(256)) * 3):
            self.assertEqual(crc32(d), zlib.crc32(d))


if __name__ == "__main__":
    unittest.main()
