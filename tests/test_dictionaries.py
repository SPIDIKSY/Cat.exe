import os
import unittest

from catlang.compiler.diagnostics import CatError, CompileError
from catlang.compiler.driver import compile_source
from catlang.vm.format import to_bytes
from tests.helpers import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EN = """fn sq(x: u32) -> u32 { return x * x; }
fn main() {
    let s: u32 = 0;
    for i in 0..5 { if i == 3 { continue; } s = s + sq(i as u32); }
    while s > 20 { s = s - 7; if s < 10 { break; } }
    print(s); write("ok"); print(true); print(false);
}"""
BE = """#мова be
функцыя sq(x: u32) -> u32 { вярнуць x * x; }
функцыя main() {
    няхай s: u32 = 0;
    для i у 0..5 { калі i == 3 { працягнуць; } s = s + sq(i як u32); }
    пакуль s > 20 { s = s - 7; калі s < 10 { перарваць; } }
    друкуй(s); пішы("ok"); друкуй(праўда); друкуй(хлусня);
}"""


class Dictionaries(unittest.TestCase):
    def test_same_bytecode_and_output(self):
        a = to_bytes(compile_source(EN, "t.cat", strip=True))
        b = to_bytes(compile_source(BE, "t.cat", strip=True))
        self.assertEqual(a, b)
        self.assertEqual(run(EN), run(BE))

    def test_english_still_works_in_be(self):
        src = "#мова be\nfn main() { print(1); друкуй(2); }"
        self.assertEqual(run(src)[0], "1\n2\n")

    def test_core_ops_in_belarusian(self):
        src = ("#мова be\nфункцыя main() { няхай a: u8 = 12; няхай b: u8 = 10;"
               " друкуй(a кот b); друкуй(a каты b); друкуй(a лапа b); друкуй(мяў a); }")
        self.assertEqual(run(src)[0], "8\n14\n6\n243\n")
        en = "fn main() { let a: u8 = 12; let b: u8 = 10; print(a cat b); print(a cats b); print(a paw b); print(meow a); }"
        self.assertEqual(to_bytes(compile_source(src, "t.cat", strip=True)),
                         to_bytes(compile_source(en, "t.cat", strip=True)))

    def test_lang_directive_english_and_errors(self):
        self.assertEqual(run("#lang en\nfn main() { print(1); }")[0], "1\n")
        with self.assertRaises(CompileError):
            compile_source("#мова zz\nfn main() { }", "t.cat")

    def test_error_line_numbers_kept(self):
        with self.assertRaises(CompileError) as c:
            compile_source("#мова be\nфункцыя main() {\n    няхай a: u8 = 300;\n}", "t.cat")
        self.assertEqual(c.exception.errors[0].line, 3)

    def test_belarusian_game(self):
        with open(os.path.join(ROOT, "examples", "guess_be.cat"), encoding="utf-8") as f:
            out, _ = run(f.read(), inputs=["abc"] * 7)
        self.assertEqual(out.count("Гэта не лік"), 7)
        self.assertIn("Не адгадаў", out)


if __name__ == "__main__":
    unittest.main()
