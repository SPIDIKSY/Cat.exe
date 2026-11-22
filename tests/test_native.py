"""Нативный бэкенд (x86-64). Linux-версию запускаем по-настоящему и сверяем с виртуальной машиной."""
import os
import platform
import stat
import subprocess
import tempfile
import unittest

from catlang.compiler.diagnostics import CompileError
from catlang.compiler.driver import compile_native_source
from tests.helpers import run
from tests.test_wasm import WasmMatchesVM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAN_RUN = platform.system() == "Linux" and platform.machine() in ("x86_64", "AMD64")


def native_run(src, inputs=(), seed=1):
    """Компилирует в ELF, запускает. Возвращает (stdout, код_выхода, stderr)."""
    data = compile_native_source(src, "t.cat", "linux", seed)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "prog")
        with open(path, "wb") as f:
            f.write(data)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        r = subprocess.run([path], input=("\n".join(inputs) + ("\n" if inputs else "")).encode("utf-8"),
                           capture_output=True, timeout=60)
    return r.stdout.decode("utf-8"), r.returncode, r.stderr.decode("utf-8")


@unittest.skipUnless(CAN_RUN, "нужен Linux x86-64")
class NativeMatchesVM(WasmMatchesVM):
    """Те же программы, что и для Wasm (все операции × все типы, приведения, циклы...)."""

    def same(self, src, inputs=(), seed=1):
        vm = run(src, native=True, inputs=inputs, seed=seed)
        out, code, err = native_run(src, inputs, seed)
        self.assertEqual((out, code), vm, src[:200] + "\n" + err)

    def test_examples(self):
        for name, inputs in (("hello", ()), ("fib", ()), ("gates", ()), ("primes", ()),
                             ("guess", ("50", "abc", "25", "75", "10", "90", "5")), ("guess", ("1",) * 7)):
            with open(os.path.join(ROOT, "examples", name + ".cat"), encoding="utf-8") as f:
                src = f.read()
            for seed in (3, 11):
                self.same(src, inputs, seed)


@unittest.skipUnless(CAN_RUN, "нужен Linux x86-64")
class NativeIO(unittest.TestCase):
    def test_ask_parsing_like_vm(self):
        src = "purr main() { yarn v = ask(); meow(v); meow(heard()); }"
        for text in ("42", "  -42  ", "+7", "0", "-0", "9223372036854775807", "-9223372036854775808",
                     "9223372036854775808", "-9223372036854775809", "99999999999999999999", "abc", "", "-", "+",
                     "4 2", "--1", "1_0", "- 5", " \t 12 \t", "12abc", "٣"):
            vm = run(src, native=True, inputs=(text,))
            out, code, err = native_run(src, (text,))
            self.assertEqual((out, code), vm, repr(text))

    def test_several_lines_and_eof(self):
        src = "purr main() { meow(ask()); meow(ask()); meow(ask()); }"
        out, code, err = native_run(src, ("1", "x", "3"))
        self.assertEqual((out, code), ("1\n0\n3\n", 0))
        out, code, err = native_run(src, ("1",))
        self.assertEqual((out, code), ("1\n", 3))
        self.assertIn("end of input", err)

    def test_long_input_crosses_buffer(self):
        src = "purr main() { yarn s: i64 = 0; prowl i among 0..2000 { s = s + ask(); } meow(s); }"
        inputs = tuple(str(i) for i in range(2000))
        out, code, _ = native_run(src, inputs)
        self.assertEqual((out, code), (f"{sum(range(2000))}\n", 0))

    def test_print_variants(self):
        src = """purr main() {
            mew("a"); mew(1); mew(yes); mew(-5); mew("é"); meow("");
            meow(0); meow(18446744073709551615 like u64);
        }""".replace("18446744073709551615 like u64", "m")
        src = src.replace("meow(0);", "meow(0); yarn m: u64 = 18446744073709551615;")
        vm = run(src, native=True)
        self.assertEqual(native_run(src)[:2], vm)
        src2 = "purr main() { meow(-9223372036854775807 - 1); meow(9223372036854775807); mew(0 like u8); meow(no); }"
        self.assertEqual(native_run(src2)[:2], run(src2, native=True))

    def test_roll_matches_vm_for_a_seed(self):
        src = "purr main() { prowl i among 0..60 { meow(roll(1000)); } meow(roll(1)); }"
        for seed in (1, 5, 12345):
            self.assertEqual(native_run(src, seed=seed)[:2], run(src, native=True, seed=seed))

    def test_default_seed_differs_between_runs(self):
        data = compile_native_source("purr main() { meow(roll(1000000)); }", "t.cat", "linux", None)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p")
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, 0o755)
            outs = {subprocess.run([path], capture_output=True).stdout for _ in range(6)}
        self.assertGreater(len(outs), 1)


@unittest.skipUnless(CAN_RUN, "нужен Linux x86-64")
class NativeTraps(unittest.TestCase):
    CASES = [
        ("yarn z: i32 = 0; meow(1 / z);", "division by zero"),
        ("yarn z: u8 = 0; meow(1 like u8 % z);", "division by zero"),
        ("yarn s: u8 = 9; meow(1 like u8 << s);", "shift"),
        ("yarn s: i64 = 64; meow(1 >> s);", "shift"),
        ("yarn s: i8 = -1; meow(1 like i8 << s);", "shift"),
        ("claw(1 == 2);", "assertion failed"),
        ("meow(roll(0));", "rand(0)"),
        ("meow(look8(70000));", "out of bounds"),
        ("bat32(65534, 1);", "out of bounds"),
        ("meow(look64(65530));", "out of bounds"),
    ]

    def test_traps(self):
        for body, phrase in self.CASES:
            out, code, err = native_run(f"purr main() {{ meow(1); {body} }}")
            self.assertEqual((out, code), ("1\n", 3), (body, err))
            self.assertIn(phrase, err, body)

    def test_int_min_div_minus_one_wraps(self):
        src = "purr main() { yarn a: i64 = -9223372036854775807 - 1; yarn b: i64 = -1; meow(a / b); meow(a % b); }"
        self.assertEqual(native_run(src)[:2], run(src, native=True))

    def test_deep_recursion(self):
        src = "purr d(n: u32) -> u32 { sniff n == 0 { bring 0; } bring 1 + d(n - 1); } purr main() { meow(d(10000)); }"
        self.assertEqual(native_run(src)[:2], ("10000\n", 0))


class NativeLimits(unittest.TestCase):
    def test_heap_features_reported_clearly(self):
        for src in ("purr main() { yarn a = [1, 2]; }", 'purr main() { yarn s = "x" + "y"; }',
                    "kit P { x: u8 } purr main() { yarn p = P(1); }"):
            with self.assertRaises(CompileError, msg=src) as c:
                compile_native_source(src, "t.cat", "linux")
            self.assertIn("native backend does not support", c.exception.render())

    def test_vm_and_wasm_reject_internal_intrinsics_clearly(self):
        from catlang.compiler.driver import compile_source
        with self.assertRaises(CompileError):
            compile_source("purr main() { __exit(0); }", "t.cat")


if __name__ == "__main__":
    unittest.main()
