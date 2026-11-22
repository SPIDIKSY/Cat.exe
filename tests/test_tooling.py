"""Инструменты для людей и ИИ: коды ошибок, JSON, форматировщик, check."""
import glob
import json
import os
import unittest

from catlang import cli
from catlang.compiler.diagnostics import CompileError, classify
from catlang.compiler.driver import compile_source
from catlang.compiler.formatter import format_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BAD = {  # программа -> ожидаемый код
    'purr main() { yarn a: u8 = 300; }': "E0101",
    'purr main() { meow(zzz); }': "E0200",
    'purr main() { zzz(); }': "E0201",
    'purr main() { yarn a: Q = 1; }': "E0202",
    'adopt nope; purr main() {}': "E0203",
    'kit P { x: u8 } purr main() { yarn p = P(1); meow(p.z); }': "E0204",
    'purr main() { yarn a = 1; yarn a = 2; }': "E0210",
    'purr f() -> u8 { } purr main() {}': "E0300",
    'purr f() {}': "E0301",
    'purr main() { scat; }': "E0302",
    'purr f() -> u8 { bring; } purr main() {}': "E0303",
    'purr f(a: u8) {} purr main() { f(); }': "E0304",
    'purr main() { yarn a: u8 = 1; yarn b: u16 = 2; meow(a + b); }': "E0100",
    'purr main() { meow(1 +); }': "E0010",
    'purr main() { meow("abc); }': "E0001",
    'purr main() { $ }': "E0003",
    'purr main() { yarn x = 12abc; }': "E0002",
    'purr main() { yarn a = []; }': "E0104",
    'purr main() { meow("a" - "b"); }': "E0102",
    'purr main() { yarn x = 5; meow(x.y); }': "E0105",
}


class ErrorCodes(unittest.TestCase):
    def test_every_error_has_its_code(self):
        for src, code in BAD.items():
            with self.assertRaises(CompileError, msg=src) as c:
                compile_source(src, "t.cat")
            codes = {e.code for e in c.exception.errors}
            self.assertIn(code, codes, (src, [e.message for e in c.exception.errors]))
            self.assertNotIn("E0999", codes, (src, [e.message for e in c.exception.errors]))

    def test_codes_are_stable_and_unique(self):
        from catlang.compiler.diagnostics import CODES
        names = [c for _, c, _ in CODES]
        self.assertEqual(classify("something unknown")[0], "E0999")
        self.assertEqual(len({n for _, _, n in CODES}), len({n for _, _, n in CODES}))
        self.assertTrue(all(c.startswith("E") and len(c) == 5 for c in names))

    def test_json_output(self):
        with self.assertRaises(CompileError) as c:
            compile_source('purr main() {\n    yarn a: u8 = 300;\n}', "t.cat")
        data = json.loads(c.exception.to_json())
        self.assertFalse(data["ok"])
        e = data["errors"][0]
        self.assertEqual((e["code"], e["line"], e["column"], e["severity"]), ("E0101", 2, 18, "error"))
        self.assertEqual(e["source"], "    yarn a: u8 = 300;")

    def test_cli_check_and_json(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            good, bad = os.path.join(d, "g.cat"), os.path.join(d, "b.cat")
            for path, text in ((good, "purr main() { meow(1); }\n"), (bad, "purr main() { meow(zzz); }\n")):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(["check", good]), 0)
                self.assertEqual(cli.main(["check", bad, "--json"]), 1)
            self.assertIn("ok", out.getvalue())
            self.assertEqual(json.loads(err.getvalue())["errors"][0]["code"], "E0200")


class Formatter(unittest.TestCase):
    UGLY = 'purr main() {\n\tyarn x = 1;   \n\n\n  sniff x == 1 {\nmeow("a { b");   // }\n   } hiss {\n meow(2);\n}\n}\n'
    GOOD = ('purr main() {\n    yarn x = 1;\n\n    sniff x == 1 {\n        meow("a { b");   // }\n'
            '    } hiss {\n        meow(2);\n    }\n}\n')

    def test_format(self):
        self.assertEqual(format_source(self.UGLY), self.GOOD)

    def test_idempotent(self):
        self.assertEqual(format_source(self.GOOD), self.GOOD)
        self.assertEqual(format_source(format_source(self.UGLY)), self.GOOD)

    def test_does_not_change_meaning(self):
        from tests.helpers import run
        self.assertEqual(run(self.UGLY, native=True), run(self.GOOD, native=True))

    def test_empty_and_crlf(self):
        self.assertEqual(format_source(""), "")
        self.assertEqual(format_source("purr main() {\r\n}\r\n"), "purr main() {\n}\n")

    def test_project_files_are_formatted(self):
        for path in glob.glob(os.path.join(ROOT, "examples", "*.cat")) + glob.glob(os.path.join(ROOT, "stdlib", "*.cat")):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(format_source(text), text, path)


if __name__ == "__main__":
    unittest.main()
