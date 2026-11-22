"""Бэкенд WebAssembly: результат должен совпадать с виртуальной машиной. Нужен Node.js (иначе пропуск)."""
import os
import shutil
import subprocess
import tempfile
import unittest

from catlang.compiler.diagnostics import CompileError
from catlang.compiler.driver import compile_wasm_source
from tests.helpers import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")


def wasm_run(src, inputs=(), seed=1):
    """Компилирует в .wasm и запускает в Node. Возвращает (вывод, код_выхода, stderr)."""
    wasm, _ = compile_wasm_source(src, "t.cat")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "p.wasm")
        with open(path, "wb") as f:
            f.write(wasm)
        r = subprocess.run([NODE, os.path.join(ROOT, "tools", "run_wasm.js"), path, "--seed", str(seed)],
                           input="\n".join(inputs) + ("\n" if inputs else ""), capture_output=True, text=True, timeout=60)
    return r.stdout, r.returncode, r.stderr


def same(test, src, inputs=(), seed=1):
    vm = run(src, native=True, inputs=inputs, seed=seed)
    w = wasm_run(src, inputs, seed)
    test.assertEqual((w[0], w[1]), vm, src[:200])


@unittest.skipUnless(NODE, "Node.js не найден")
class WasmMatchesVM(unittest.TestCase):
    TYPES = [("u8", 8, False), ("u16", 16, False), ("u32", 32, False), ("u64", 64, False),
             ("i8", 8, True), ("i16", 16, True), ("i32", 32, True), ("i64", 64, True)]

    def edge(self, bits, signed):
        lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        vals = {0, 1, 2, 3, 7, hi, hi - 1, lo, lo + 1, 100 % (hi + 1) if hi > 100 else hi // 2}
        if signed:
            vals |= {-1, -2, -7}
        return sorted(v for v in vals if lo <= v <= hi)

    def test_operations_all_types(self):
        for name, bits, signed in self.TYPES:
            vals = self.edge(bits, signed)
            ops = ["a + b", "a - b", "a * b", "a C b", "a A b", "a S b", "T a", "a == b", "a != b",
                   "a < b", "a <= b", "a > b", "a >= b"]
            if signed:
                ops.append("-a")
            fns = []
            for i, op in enumerate(ops):
                rt = "bool" if any(c in op for c in ("==", "!=", "<", ">")) else name
                fns.append(f"purr f{i}(a: {name}, b: {name}) -> {rt} {{ bring {op}; }}")
            fns.append(f"purr dv(a: {name}, b: {name}) -> {name} {{ bring a / b; }}")
            fns.append(f"purr rm(a: {name}, b: {name}) -> {name} {{ bring a % b; }}")
            fns.append(f"purr sl(a: {name}, b: {name}) -> {name} {{ bring a << b; }}")
            fns.append(f"purr sr(a: {name}, b: {name}) -> {name} {{ bring a >> b; }}")
            body = []
            amounts = sorted({0, 1, bits - 1, bits // 2})
            for a in vals:
                for b in vals:
                    for i in range(len(ops)):
                        body.append(f"meow(f{i}({a}, {b}));")
                    if b != 0:
                        body.append(f"meow(dv({a}, {b})); meow(rm({a}, {b}));")
                for b in amounts:
                    body.append(f"meow(sl({a}, {b})); meow(sr({a}, {b}));")
            src = "\n".join(fns) + "\npurr main() {\n" + "\n".join(body) + "\n}\n"
            same(self, src)

    def test_casts_between_all_types(self):
        names = [n for n, _, _ in self.TYPES]
        fns = [f"purr c_{a}_{b}(x: {a}) -> {b} {{ bring x like {b}; }}" for a in names for b in names]
        body = []
        for a, bits, signed in self.TYPES:
            for v in self.edge(bits, signed):
                for b in names:
                    body.append(f"meow(c_{a}_{b}({v}));")
        body.append("meow(yes like u8); meow(no like i64);")
        same(self, "\n".join(fns) + "\npurr main() {\n" + "\n".join(body) + "\n}\n")

    def test_control_flow(self):
        src = """
        purr collatz(n: u64) -> u32 {
            yarn steps: u32 = 0;
            chase n != 1 {
                sniff (n C 1) == 1 { n = n * 3 + 1; } hiss { n = n >> 1; }
                steps = steps + 1;
            }
            bring steps;
        }
        purr main() {
            prowl i among 1..30 {
                sniff i % 7 == 0 { hop; }
                sniff i > 25 { scat; }
                mew(collatz(i like u64)); mew(" ");
            }
            meow("");
            prowl a among 0..3 { prowl b among 0..4 { sniff b == 2 { scat; } mew(a * 10 + b); mew(","); } }
            meow("");
            yarn t = yes; yarn f = no;
            meow(t && f); meow(t || f); meow(f || f); meow(t && t); meow(T t);
            yarn i = 0;
            chase yes { i = i + 1; sniff i < 5 { hop; } scat; }
            meow(i);
        }"""
        same(self, src)

    def test_nested_ifs_and_early_return(self):
        src = """
        purr sign(x: i32) -> i32 {
            sniff x < 0 { bring -1; } hiss sniff x == 0 { bring 0; } hiss { bring 1; }
        }
        purr find(limit: u32) -> u32 {
            prowl i among 0..limit { sniff i * i > 50 { bring i; } }
            bring 999;
        }
        purr main() { meow(sign(-5)); meow(sign(0)); meow(sign(9)); meow(find(100)); meow(find(3)); }"""
        same(self, src)

    def test_exit_code_and_u64_printing(self):
        src = "purr main() -> i32 { yarn m: u64 = 18446744073709551615; meow(m); meow(-9223372036854775807 - 1); bring 44; }"
        same(self, src)

    def test_examples(self):
        for name, inputs in (("hello", ()), ("fib", ()), ("gates", ()), ("primes", ()),
                             ("tictactoe", ("5", "1", "9", "3", "7", "2", "4", "6", "8")),
                             ("tictactoe", tuple(str(i % 9 + 1) for i in range(40))),
                             ("guess", ("50", "abc", "25", "75", "10", "90", "5")),
                             ("guess", ("1",) * 7)):
            with open(os.path.join(ROOT, "examples", name + ".cat"), encoding="utf-8") as f:
                src = f.read()
            for seed in (3, 11):
                same(self, src, inputs, seed)

    def test_roll_same_generator(self):
        same(self, "purr main() { prowl i among 0..50 { meow(roll(1000)); } }", seed=12345)


@unittest.skipUnless(NODE, "Node.js не найден")
class WasmTraps(unittest.TestCase):
    def trap(self, body):
        out, code, err = wasm_run(f"purr main() {{ {body} }}")
        self.assertEqual(code, 3, (out, err))
        return err

    def test_traps(self):
        self.assertIn("division by zero", self.trap("yarn z: i32 = 0; meow(1 / z);"))
        self.assertIn("division by zero", self.trap("yarn z: u8 = 0; meow(1 like u8 % z);"))
        self.trap("yarn s: u8 = 9; meow(1 like u8 << s);")
        self.trap("yarn s: i64 = 64; meow(1 >> s);")
        self.trap("yarn s: i8 = -1; meow(1 like i8 << s);")
        self.trap("claw(1 == 2);")
        self.assertIn("end of input", self.trap("meow(ask());"))
        self.assertIn("range is empty", self.trap("meow(roll(0));"))

    def test_trap_matches_vm_trap(self):
        from catlang.vm.vm import CatTrap
        for body in ("yarn z: i32 = 0; meow(1 / z);", "yarn s: u8 = 9; meow(1 like u8 << s);", "claw(no);"):
            with self.assertRaises(CatTrap):
                run(f"purr main() {{ {body} }}", native=True)


@unittest.skipUnless(NODE, "Node.js не найден")
class WasmLimits(unittest.TestCase):
    def test_heap_programs_compile(self):
        for src in ("purr main() { yarn a = [1, 2]; }", 'purr main() { yarn s = "x" + "y"; }',
                    "kit P { x: u8 } purr main() { yarn p = P(1); }", 'purr main() { bury("x"); }'):
            wasm, _ = compile_wasm_source(src, "t.cat")
            self.assertGreater(len(wasm), 8)

    def test_unused_unsupported_functions_are_skipped(self):
        src = "purr unused() { yarn a = [1]; } purr main() { meow(1); }"
        self.assertEqual(wasm_run(src)[:2], ("1\n", 0))

    def test_html_page(self):
        from catlang import cli
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.cat")
            with open(p, "w", encoding="utf-8") as f:
                f.write('purr main() { meow("мяу"); }\n')
            self.assertEqual(cli.main(["wasm", p, "--html"]), 0)
            with open(os.path.join(d, "a.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertIn("WebAssembly.instantiate", page)
            self.assertIn("atob(", page)
            self.assertTrue(os.path.getsize(os.path.join(d, "a.wasm")) > 8)
            script = page[page.index("<script>") + 8:page.index("</script>")]
            js = os.path.join(d, "page.js")
            with open(js, "w", encoding="utf-8") as f:
                f.write(script)
            r = subprocess.run([NODE, "--check", js], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)  # JS страницы синтаксически верен


if __name__ == "__main__":
    unittest.main()
