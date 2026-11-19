import os
import unittest

from catlang.compiler.diagnostics import CompileError
from catlang.compiler.driver import compile_source
from catlang.vm.vm import CatTrap
from tests.helpers import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(body):
    return f"fn main() {{ {body} }}"


class Loops(unittest.TestCase):
    def test_for(self):
        self.assertEqual(run(main("let s: u32 = 0; for i in 0..5 { s = s + i as u32; } print(s);"))[0], "10\n")

    def test_for_typed_range(self):
        out, _ = run(main("let n: u8 = 3; for i in 0..n { print(i); }"))
        self.assertEqual(out, "0\n1\n2\n")

    def test_for_empty_and_max(self):
        self.assertEqual(run(main("for i in 5..5 { print(i); } for j in 254 as u8..255 as u8 { print(j); }"))[0], "254\n")

    def test_break_continue(self):
        src = main("for i in 0..10 { if i == 2 { continue; } if i == 5 { break; } print(i); }")
        self.assertEqual(run(src)[0], "0\n1\n3\n4\n")
        src = main("let i = 0; while true { i = i + 1; if i % 2 == 0 { continue; } if i > 6 { break; } print(i); }")
        self.assertEqual(run(src)[0], "1\n3\n5\n")

    def test_nested_break_inner_only(self):
        src = main("for i in 0..2 { for j in 0..5 { if j == 1 { break; } print(i * 10 + j); } }")
        self.assertEqual(run(src)[0], "0\n10\n")

    def test_break_outside_loop(self):
        with self.assertRaises(CompileError):
            compile_source(main("break;"), "t.cat")

    def test_for_errors(self):
        for body in ("for i in true..false { }", "for i in 0 as u8..300 as u16 { }"):
            with self.assertRaises(CompileError):
                compile_source(main(body), "t.cat")


class ShortCircuit(unittest.TestCase):
    def test_and_or(self):
        out, _ = run(main("print(true && false); print(true || false); print(false || false); print(true && true);"))
        self.assertEqual(out, "false\ntrue\nfalse\ntrue\n")

    def test_short_circuit_skips_right_side(self):
        # правая часть делит на ноль, но не должна выполниться
        src = "fn main() { let z: i32 = 0; if z != 0 && 10 / z > 1 { print(1); } if z == 0 || 10 / z > 1 { print(2); } }"
        self.assertEqual(run(src, optimize=False)[0], "2\n")
        self.assertEqual(run(src)[0], "2\n")

    def test_precedence(self):
        # && сильнее ||; сравнения сильнее обоих
        out, _ = run(main("print(true || false && false); print(1 < 2 && 2 < 3);"))
        self.assertEqual(out, "true\ntrue\n")

    def test_bool_only(self):
        with self.assertRaises(CompileError):
            compile_source(main("print(1 && 2);"), "t.cat")


class InputOutput(unittest.TestCase):
    def test_write_no_newline(self):
        self.assertEqual(run(main('write("a"); write(1); write(true); print("!");'))[0], "a1true!\n")

    def test_read_int(self):
        src = main("let a = read_int(); let ok1 = input_ok(); let b = read_int(); print(a); print(ok1);"
                   " print(b); print(input_ok());")
        self.assertEqual(run(src, inputs=["  -42 ", "abc"])[0], "-42\ntrue\n0\nfalse\n")

    def test_read_int_rejects_weird(self):
        for text in ("1_0", "4 2", "--1", "", "٣", "99999999999999999999"):
            out, _ = run(main("read_int(); print(input_ok());"), inputs=[text])
            self.assertEqual(out, "false\n", text)

    def test_end_of_input_traps(self):
        with self.assertRaises(CatTrap) as c:
            run(main("read_int();"))
        self.assertIn("end of input", c.exception.message)


class Random(unittest.TestCase):
    def test_range_and_repeatable(self):
        src = main("for i in 0..200 { let r = rand(6); assert(r < 6); print(r); }")
        a, b = run(src, seed=7)[0], run(src, seed=7)[0]
        self.assertEqual(a, b)
        self.assertNotEqual(a, run(src, seed=8)[0])
        self.assertEqual(set(a.split()), {"0", "1", "2", "3", "4", "5"})

    def test_rand_zero_traps(self):
        with self.assertRaises(CatTrap):
            run(main("print(rand(0));"))

    def test_gate_mode_same(self):
        src = main("for i in 0..5 { print(rand(100) + 1); }")
        self.assertEqual(run(src, seed=3), run(src, seed=3, gates=True))


class Game(unittest.TestCase):
    def play(self, inputs, seed=5):
        with open(os.path.join(ROOT, "examples", "guess.cat"), encoding="utf-8") as f:
            return run(f.read(), inputs=inputs, seed=seed)

    def secret(self):
        for n in range(1, 101):  # ищем загаданное число перебором
            out = self.play([str(n)] + ["0"] * 6)[0]
            if "Угадал" in out:
                return n

    def test_win_and_hints(self):
        n = self.secret()
        out, _ = self.play(["1000", "0", str(n)])
        self.assertIn("Меньше", out)
        self.assertIn("Больше", out)
        self.assertIn("Угадал", out)

    def test_lose_reveals_secret(self):
        n = self.secret()
        wrong = "1" if n != 1 else "2"
        out, code = self.play([wrong] * 7)
        self.assertIn(f"Я загадал: {n}", out)
        self.assertEqual(code, 0)

    def test_bad_input_costs_try(self):
        out, _ = self.play(["abc"] * 7)
        self.assertEqual(out.count("Это не число"), 7)


if __name__ == "__main__":
    unittest.main()
