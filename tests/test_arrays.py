"""Массивы, строки, куча (нативный синтаксис)."""
import unittest

from catlang.compiler.diagnostics import CompileError
from catlang.compiler.driver import compile_source
from catlang.vm import format as F
from catlang.vm.vm import VM, CatTrap
from tests.helpers import run


def main(body, pre=""):
    return f"{pre}\npurr main() {{ {body} }}"


def out(src, **kw):
    return run(src, native=True, **kw)[0]


class Arrays(unittest.TestCase):
    def test_repeat_literal_index_assign(self):
        self.assertEqual(out(main("yarn a: [i32] = [0; 3]; a[1] = -5; yarn b = [7, 8, 9];"
                                  " meow(a[0]); meow(a[1]); meow(b[2]); meow(stretch(b));")),
                         "0\n-5\n9\n3\n")

    def test_element_types_wrap(self):
        self.assertEqual(out(main("yarn a = [250 like u8; 2]; a[0] = a[0] + 10; meow(a[0]); meow(a[1]);")), "4\n250\n")

    def test_bool_and_nested(self):
        src = main("yarn f = [no; 3]; f[1] = yes; meow(f[0]); meow(f[1]);"
                   " yarn g = [[1, 2], [3, 4]]; g[1][0] = 9; meow(g[1][0]); meow(g[0][1]);")
        self.assertEqual(out(src), "false\ntrue\n9\n2\n")

    def test_arrays_are_references(self):
        src = ("purr fill(a: [u32]) { prowl i among 0..stretch(a) { a[i] = i * 2; } }"
               + main("yarn a = [0 like u32; 4]; fill(a); yarn b = a; b[0] = 99; meow(a[0]); meow(a[3]);"))
        self.assertEqual(out(src), "99\n6\n")

    def test_array_from_function_and_empty(self):
        src = ("purr make(n: u32) -> [u32] { yarn r: [u32] = []; bring [n; n]; }"
               + main("yarn x = make(3); meow(stretch(x)); meow(x[2]); yarn e: [u8] = []; meow(stretch(e));"))
        self.assertEqual(out(src), "3\n3\n0\n")

    def test_sieve(self):
        src = main("yarn s = [yes; 30]; yarn n = 0 like u32;"
                   " prowl i among 2..stretch(s) { sniff s[i] { n = n + 1; yarn j = i * 2; chase j < 30 { s[j] = no; j = j + i; } } }"
                   " meow(n);")
        self.assertEqual(out(src), "10\n")

    def test_gate_mode_same(self):
        src = main("yarn a = [3, 1, 2]; meow(a[0] + a[1] * a[2]);")
        self.assertEqual(run(src, native=True), run(src, native=True, gates=True))


class Strings(unittest.TestCase):
    def test_concat_compare_size_index(self):
        src = main('yarn s = "ab" + "cd"; meow(s); meow(stretch(s)); meow(s[2]); meow(s == "abcd"); meow(s != "abcd"); meow("" + "");')
        self.assertEqual(out(src), "abcd\n4\n99\ntrue\nfalse\n\n")

    def test_scribble_and_unicode(self):
        self.assertEqual(out(main('meow("Счёт: " + scribble(-12)); meow(stretch("мяу"));')), "Счёт: -12\n6\n")

    def test_listen(self):
        self.assertEqual(out(main('yarn s = listen(); meow("Привет, " + s + "!");'), inputs=["кот"]), "Привет, кот!\n")

    def test_string_in_arrays_and_params(self):
        src = ('purr twice(s: str) -> str { bring s + s; }'
               + main('yarn n = ["a", "b"]; n[0] = twice(n[1]); meow(n[0]);'))
        self.assertEqual(out(src), "bb\n")

    def test_loop_building_string(self):
        self.assertEqual(out(main('yarn s = ""; prowl i among 0..4 { s = s + scribble(i); } meow(s);')), "0123\n")


class Traps(unittest.TestCase):
    def trap(self, src, **kw):
        with self.assertRaises(CatTrap) as c:
            run(src, native=True, **kw)
        return c.exception.message

    def test_index_out_of_bounds(self):
        self.assertIn("out of bounds", self.trap(main("yarn a = [1, 2]; yarn i: u32 = 2; meow(a[i]);")))
        self.assertIn("out of bounds", self.trap(main("yarn a = [1, 2]; yarn i: u32 = 5; a[i] = 1;")))
        self.assertIn("out of bounds", self.trap(main('meow("ab"[2 like u32]);')))

    def test_out_of_memory(self):
        self.assertIn("out of memory", self.trap(main("yarn a = [0 like u64; 4000000000 like u32]; meow(stretch(a));")))
        self.assertIn("out of memory", self.trap(main('yarn s = "x"; chase yes { s = s + s; }')))

    def test_forged_reference_rejected(self):
        # байткод, где «массивом» объявлено число из пользовательской памяти
        src = "purr main() { yarn x: u32 = 100; meow(x); }"
        p = compile_source(src.replace("purr", "purr").replace("yarn", "yarn"), "t.cat")
        code = bytearray(p.code)
        from catlang.vm.opcodes import OPS
        code[code.index(0x80)] = OPS["ALEN"][0]  # PRINTI -> ALEN
        p.code = bytes(code)
        with self.assertRaises(CatTrap) as c:
            VM(p).run()
        self.assertIn("invalid reference", c.exception.message)


class Errors(unittest.TestCase):
    def has(self, src, text):
        with self.assertRaises(CompileError) as c:
            compile_source(src, "t.cat")
        self.assertTrue(any(text in e.message for e in c.exception.errors), c.exception.render())

    def test_type_errors(self):
        self.has(main("yarn a = [1, 2]; a[0] = yes;"), "type mismatch")
        self.has(main('yarn a = [1, 2]; meow(a["x"]);'), "type mismatch")
        self.has(main("yarn a = 5; meow(a[0]);"), "cannot index")
        self.has(main('yarn s = "x"; s[0] = 1 like u8;'), "immutable")
        self.has(main('meow("a" + 1);'), "type mismatch")
        self.has(main('meow("a" - "b");'), "cannot be applied")
        self.has(main("yarn a = [1, 2]; meow(a < a);"), "cannot be applied")
        self.has(main("yarn a: [u8] = [1, 2, 3, 300];"), "does not fit")
        self.has(main("yarn e = [];"), "cannot infer")
        self.has(main("yarn a = [1, no];"), "type mismatch")
        self.has(main("meow(stretch(5));"), "needs an array or a string")
        self.has(main("meow(scribble(yes));"), "needs an integer")
        self.has(main("yarn a = [1]; meow(a);"), "cannot print")
        self.has("purr f() -> [u8] { bring [1, 2]; } purr main() { yarn x: [u16] = f(); }", "type mismatch")

    def test_syntax_errors(self):
        self.has(main("5 = 6;"), "only a variable")
        self.has(main("yarn a = [1, 2;"), "expected")


class TicTacToe(unittest.TestCase):
    def test_always_finishes_with_a_result(self):
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "tictactoe.cat")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        results = set()
        for seed in range(1, 21):
            o, _ = run(src, native=True, seed=seed, inputs=[str(i % 9 + 1) for i in range(60)])
            res = [x for x in ("Ты победил", "Котик победил", "Ничья") if x in o]
            self.assertEqual(len(res), 1, (seed, o))
            results.add(res[0])
        self.assertIn("Котик победил", results)

    def test_input_validation(self):
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "tictactoe.cat")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        o, _ = run(src, native=True, seed=1, inputs=["abc", "0", "10", "5", "5"] + ["1", "2", "3", "4", "6", "7", "8", "9"] * 2)
        self.assertEqual(o.count("Нужно число от 1 до 9."), 3)
        self.assertIn("Клетка занята.", o)


class Format(unittest.TestCase):
    def test_roundtrip_with_strings_and_arrays(self):
        p = compile_source(main('yarn a = [1, 2, 3]; meow("n=" + scribble(a[2]));').replace("purr", "purr"), "t.cat")
        q = F.from_bytes(F.to_bytes(p))
        o = []
        VM(q, out=o.append).run()
        self.assertEqual("".join(o), "n=3\n")


if __name__ == "__main__":
    unittest.main()
