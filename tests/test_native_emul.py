"""PE (Windows) и Mach-O (macOS Intel): готовые файлы разбираются сторонними библиотеками и выполняются в эмуляторе.
Запуск: нужны unicorn, pefile, macholib (pip install unicorn pefile macholib); без них тесты пропускаются."""
import os
import unittest

from catlang.compiler.driver import compile_native_source
from tests import emulator
from tests.helpers import run
from tests.test_wasm import WasmMatchesVM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = unittest.skipUnless(emulator.AVAILABLE, "нет unicorn/pefile/macholib")


def emu_run(src, target, inputs=(), seed=1):
    data = compile_native_source(src, "t.cat", target, seed)
    stdin = ("\n".join(inputs) + ("\n" if inputs else "")).encode("utf-8")
    runner = emulator.run_pe if target == "windows" else emulator.run_macho
    out, code, err, problems = runner(data, stdin)
    return out, code, err, problems


def make_tests(target):
    class Matches(WasmMatchesVM):
        def same(self, src, inputs=(), seed=1):
            vm = run(src, native=True, inputs=inputs, seed=seed)
            out, code, err, problems = emu_run(src, target, inputs, seed)
            self.assertEqual(problems, [], src[:200])
            self.assertEqual((out, code), vm, src[:200] + "\n" + err)

        def test_examples(self):
            for name, inputs in (("hello", ()), ("fib", ()), ("gates", ()), ("primes", ()),
                                 ("guess", ("50", "abc", "25", "75", "10", "90", "5")), ("guess", ("1",) * 7)):
                with open(os.path.join(ROOT, "examples", name + ".cat"), encoding="utf-8") as f:
                    self.same(f.read(), inputs, 3)

    class IO(unittest.TestCase):
        def test_ask_roll_traps(self):
            src = "purr main() { yarn v = ask(); meow(v); meow(heard()); meow(roll(100)); meow(ask()); }"
            for text in ("42", "  -7 ", "abc", "99999999999999999999", "4 2"):
                vm = run(src, native=True, inputs=(text, "5"))
                out, code, err, problems = emu_run(src, target, (text, "5"))
                self.assertEqual((problems, out, code), ([], *vm), text)
            out, code, err, problems = emu_run(src, target, ("1",))
            self.assertEqual((problems, code), ([], 3))
            self.assertIn("end of input", err)
            for body, phrase in (("yarn z: i32 = 0; meow(1 / z);", "division by zero"),
                                 ("claw(no);", "assertion failed"), ("meow(look8(70000));", "out of bounds")):
                out, code, err, problems = emu_run(f"purr main() {{ meow(1); {body} }}", target)
                self.assertEqual((problems, out, code), ([], "1\n", 3), body)
                self.assertIn(phrase, err)

        def test_exit_code_and_unicode_and_recursion(self):
            src = ('purr d(n: u32) -> u32 { sniff n == 0 { bring 0; } bring 1 + d(n - 1); }'
                   ' purr main() -> i32 { meow("Мяу, 猫!"); meow(d(10000)); bring 42; }')
            out, code, err, problems = emu_run(src, target)
            self.assertEqual((problems, out, code), ([], "Мяу, 猫!\n10000\n", 42))

    Matches.__name__, IO.__name__ = f"{target.capitalize()}Matches", f"{target.capitalize()}IO"
    return SKIP(Matches), SKIP(IO)


WindowsMatches, WindowsIO = make_tests("windows")
MacosMatches, MacosIO = make_tests("macos")

if __name__ == "__main__":
    unittest.main()
