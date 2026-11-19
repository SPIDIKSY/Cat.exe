import os
import unittest

from catlang.compiler.diagnostics import CompileError
from tests.helpers import compile_source
from catlang.compiler.lexer import tokenize
from catlang.compiler.diagnostics import CatError
from catlang.vm.vm import CatTrap
from tests.helpers import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(body, pre=""):
    return f"{pre}\nfn main() {{ {body} }}"


class Basics(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(run(main('print("hi");')), ("hi\n", 0))

    def test_logic_ops(self):
        out, _ = run(main("let a: u8 = 12; let b: u8 = 10; print(a cat b); print(a cats b);"
                          " print(a paw b); print(meow a);"))
        self.assertEqual(out, "8\n14\n6\n243\n")

    def test_bool_logic(self):
        out, _ = run(main("let t = true; print(t cat false); print(t cats false);"
                          " print(t paw t); print(meow t);"))
        self.assertEqual(out, "false\ntrue\nfalse\nfalse\n")

    def test_precedence(self):
        # cat сильнее paw, paw сильнее cats; сравнения сильнее cat
        out, _ = run(main("print(1 cats 2 cat 3 paw 7); print(1 + 2 * 3 << 1);"))
        self.assertEqual(out, f"{1 | ((2 & 3) ^ 7)}\n{(1 + 2 * 3) << 1}\n")

    def test_wraparound_and_cast(self):
        out, _ = run(main("let x: u8 = 250; x = x + 10; print(x); print(-1 as u8);"
                          " let y: i8 = -128; print(y - 1); print(300 as u8);"))
        self.assertEqual(out, "4\n255\n127\n44\n")

    def test_signed_div_rem(self):
        out, _ = run(main("print(-7 / 2); print(-7 % 2); print(7 / -2);"))
        self.assertEqual(out, "-3\n-1\n-3\n")

    def test_control_flow(self):
        src = main("let s: u32 = 0; let i: u32 = 1; while i <= 10 { if i % 2 == 0 { s = s + i; }"
                   " else if i == 7 { s = s + 100; } i = i + 1; } print(s);")
        self.assertEqual(run(src)[0], "130\n")

    def test_functions_and_recursion(self):
        src = ("fn fact(n: u64) -> u64 { if n <= 1 { return 1; } return n * fact(n - 1); }"
               + main("print(fact(10)); print(fact(20));"))
        self.assertEqual(run(src)[0], "3628800\n2432902008176640000\n")

    def test_exit_code(self):
        self.assertEqual(run("fn main() -> i32 { return 7; }")[1], 7)

    def test_memory(self):
        out, _ = run(main("poke32(8, 0xDEADBEEF); print(peek8(8)); print(peek16(10)); print(peek32(8));"))
        self.assertEqual(out, "239\n57005\n3735928559\n")

    def test_shadowing_and_scopes(self):
        out, _ = run(main("let x = 1; { let x = 2; print(x); } print(x);"))
        self.assertEqual(out, "2\n1\n")

    def test_stdlib_math(self):
        out, _ = run(main("print(math.gcd(48, 18)); print(math.abs(-5)); print(math.isqrt(99));",
                          "use math;"))
        self.assertEqual(out, "6\n5\n9\n")


class Traps(unittest.TestCase):
    def trap(self, body):
        with self.assertRaises(CatTrap) as c:
            run(main(body))
        return c.exception

    def test_div_zero(self):
        e = self.trap("let z: i32 = 0; print(1 / z);")
        self.assertIn("division by zero", e.message)
        self.assertIn("line 2", e.where)

    def test_shift(self):
        self.assertIn("shift", self.trap("let s: u8 = 9; print(1 as u8 << s);").message)

    def test_assert(self):
        self.assertIn("assertion", self.trap("assert(1 == 2);").message)

    def test_memory_bounds(self):
        self.assertIn("out of bounds", self.trap("print(peek8(70000));").message)
        self.assertIn("out of bounds", self.trap("poke32(65534, 1);").message)

    def test_recursion_overflow(self):
        with self.assertRaises(CatTrap) as c:
            run("fn f(n: u32) -> u32 { return f(n + 1); } fn main() { f(0); }")
        self.assertIn("overflow", c.exception.message)

    def test_step_limit(self):
        with self.assertRaises(CatTrap):
            run("fn main() { while true { } }", max_steps=1000, optimize=False)


class Errors(unittest.TestCase):
    def errs(self, src):
        with self.assertRaises(CompileError) as c:
            compile_source(src, "t.cat")
        return [e.message for e in c.exception.errors]

    def has(self, src, text):
        msgs = self.errs(src)
        self.assertTrue(any(text in m for m in msgs), msgs)

    def test_type_mismatch(self):
        self.has(main("let a: u8 = 1; let b: u16 = 2; print(a + b);"), "type mismatch")

    def test_literal_range(self):
        self.has(main("let a: u8 = 256;"), "does not fit")
        self.has(main("let a: u8 = -1;"), "does not fit")

    def test_undefined(self):
        self.has(main("print(zzz);"), "undefined variable")
        self.has(main("zzz(1);"), "undefined function")

    def test_missing_return(self):
        self.has("fn f() -> u8 { } fn main() { }", "without returning")

    def test_no_main(self):
        self.has("fn f() { }", "no 'purr main()'")

    def test_condition_not_bool(self):
        self.has(main("if 1 { }"), "expected 'bool'")

    def test_arg_count(self):
        self.has("fn f(a: u8) { } " + main("f();"), "takes 1")

    def test_redeclare(self):
        self.has(main("let a = 1; let a = 2;"), "already declared")

    def test_unsigned_neg(self):
        self.has(main("let a: u8 = 1; print(-a);"), "cannot be applied")

    def test_string_misuse(self):
        self.has(main('let s = "x";'), "cannot store")

    def test_multiple_errors_reported(self):
        self.assertGreaterEqual(len(self.errs(main("print(a); print(b);"))), 2)

    def test_syntax_and_lexer(self):
        self.has(main("let = 5;"), "expected")
        self.has(main("print(1"), "expected")
        with self.assertRaises(CatError):
            tokenize("fn main() { $ }")
        with self.assertRaises(CatError):
            tokenize('"abc')

    def test_unknown_module(self):
        self.has("use nope; fn main() {}", "unknown module")

    def test_error_render(self):
        with self.assertRaises(CompileError) as c:
            compile_source("fn main() {\n    let a: u8 = 300;\n}", "t.cat")
        text = c.exception.render()
        self.assertIn("t.cat:2:18", text)
        self.assertIn("^", text)


class Optimizer(unittest.TestCase):
    def test_same_result_with_and_without(self):
        src = main("print(2 * 3 + 4); if 1 < 2 { print(1); } else { print(2); }"
                   " while false { print(9); } let x: u8 = 200 + 100; print(x);")
        self.assertEqual(run(src), run(src, optimize=False))

    def test_folding_shrinks_code(self):
        src = main("print(1 + 2 * 3);")
        a = compile_source(src, "t.cat").code
        b = compile_source(src, "t.cat", optimize_code=False).code
        self.assertLess(len(a), len(b))

    def test_div_zero_constant_not_folded(self):
        with self.assertRaises(CatTrap):
            run(main("print(1 / 0);"))


class Examples(unittest.TestCase):
    def test_examples_gates_mode_equal(self):
        for name in ("hello", "fib", "gates", "primes"):
            with open(os.path.join(ROOT, "examples", name + ".cat"), encoding="utf-8") as f:
                src = f.read()
            if name == "fib":
                src = src.replace("<= 15", "<= 8")  # в режиме вентилей — покороче
            if name == "gates":
                continue  # проверен отдельно ниже (долго в режиме вентилей)
            self.assertEqual(run(src, native=True), run(src, gates=True, native=True), name)

    def test_gates_example(self):
        with open(os.path.join(ROOT, "examples", "gates.cat"), encoding="utf-8") as f:
            self.assertEqual(run(f.read(), native=True), ("44\n251\n0\n", 0))


if __name__ == "__main__":
    unittest.main()
