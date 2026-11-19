"""Тесты на нативном синтаксисе: кошачьи слова и сердце C/A/T/S."""
import unittest

from catlang.compiler.diagnostics import CompileError
from catlang.compiler.driver import compile_source
from catlang.compiler.vocab import SURFACE
from tests.helpers import run

LOOPS = """
purr sq(x: u32) -> u32 { bring x * x; }
purr main() {
    yarn total: u32 = 0;
    prowl i among 0..8 {
        sniff i == 2 { hop; }
        sniff i == 6 { scat; }
        total = total + sq(i like u32);
    }
    yarn n: i32 = 3;
    chase n > 0 { n = n - 1; }
    sniff n == 0 && yes { meow(total); } hiss { meow("bad"); }
    meow(no);
}
"""


class CatWords(unittest.TestCase):
    def test_all_keywords(self):
        # 0+1+9+16+25 = 51
        self.assertEqual(run(LOOPS, native=True)[0], "51\nfalse\n")

    def test_heart_letters(self):
        src = ("purr main() { yarn a: u8 = 12; yarn b: u8 = 10;"
               " meow(a C b); meow(a A b); meow(a S b); meow(T a); }")
        self.assertEqual(run(src, native=True)[0], "8\n14\n6\n243\n")

    def test_heart_on_bool(self):
        src = "purr main() { meow(yes C no); meow(yes A no); meow(yes S yes); meow(T yes); }"
        self.assertEqual(run(src, native=True)[0], "false\ntrue\nfalse\nfalse\n")

    def test_heart_precedence(self):
        # C сильнее S, S сильнее A
        src = "purr main() { meow(1 A 2 C 3 S 7); }"
        self.assertEqual(run(src, native=True)[0], f"{1 | ((2 & 3) ^ 7)}\n")

    def test_builtins(self):
        src = """purr main() {
            mew("a"); mew(1); meow("!");
            bat32(8, 0xDEADBEEF); meow(look8(8));
            yarn r = roll(6); claw(r < 6);
            yarn v = ask(); meow(v); meow(heard());
        }"""
        out, _ = run(src, native=True, inputs=["41"])
        self.assertEqual(out, "a1!\n239\n41\ntrue\n")

    def test_adopt_module(self):
        self.assertEqual(run("adopt math; purr main() { meow(math.gcd(12, 18)); }", native=True)[0], "6\n")

    def test_old_english_words_mean_nothing(self):
        # print/rand больше не встроенные, `fn` — просто имя
        for src in ("purr main() { print(1); }", "purr main() { yarn x = rand(5); }",
                    "fn main() { }"):
            with self.assertRaises(CompileError):
                compile_source(src, "t.cat")
        # старые слова годятся как имена переменных и функций
        src = "purr cat(fn: u8) -> u8 { bring fn; } purr main() { yarn let = cat(5); meow(let); }"
        self.assertEqual(run(src, native=True)[0], "5\n")

    def test_error_messages_use_cat_words(self):
        for src, word in (("purr main() { yarn a: u8 = 1; meow(a A yes); }", "A 'bool'"),
                          ("purr main() { scat; }", "'scat'"),
                          ("purr f() -> u8 { bring; } purr main() {}", "'bring'"),
                          ("purr f() { }", "purr main()")):
            with self.assertRaises(CompileError) as c:
                compile_source(src, "t.cat")
            self.assertTrue(any(word in e.message for e in c.exception.errors), (src, c.exception.render()))

    def test_vocabulary_has_no_duplicates(self):
        self.assertEqual(len(set(SURFACE.values())), len(SURFACE))


if __name__ == "__main__":
    unittest.main()
