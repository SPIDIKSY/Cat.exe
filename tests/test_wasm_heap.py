"""Куча в WebAssembly (массивы, строки, структуры, bury): совпадение с виртуальной машиной."""
import unittest

from catlang.vm.vm import CatTrap
from tests.helpers import run
from tests.test_wasm import NODE, same, wasm_run

P = "kit P { x: i32, y: i32 }"
NODE_CASES = {
    "arrays": ("""purr fill(a: [u32]) { prowl i among 0..stretch(a) { a[i] = i * 2; } }
        purr make(n: u32) -> [u32] { bring [n; n]; }
        purr main() {
            yarn a: [i32] = [0; 3]; a[1] = -5; yarn b = [7, 8, 9];
            meow(a[0]); meow(a[1]); meow(b[2]); meow(stretch(b));
            yarn c = [250 like u8; 2]; c[0] = c[0] + 10; meow(c[0]); meow(c[1]);
            yarn f = [no; 3]; f[1] = yes; meow(f[0]); meow(f[1]);
            yarn g = [[1, 2], [3, 4]]; g[1][0] = 9; meow(g[1][0]); meow(g[0][1]);
            yarn d = [0 like u32; 4]; fill(d); yarn e = d; e[0] = 99; meow(d[0]); meow(d[3]);
            yarn m = make(3); meow(stretch(m)); meow(m[2]);
            yarn w = [0 like u64; 2]; w[1] = 18446744073709551615; meow(w[1]);
            yarn h = [-1 like i16; 2]; h[0] = h[0] - 32767; meow(h[0]); meow(h[1]);
        }""", ()),
    "sieve": ("""purr main() {
            yarn s = [yes; 100]; yarn n = 0 like u32;
            prowl i among 2..stretch(s) { sniff s[i] { n = n + 1; yarn j = i * 2; chase j < 100 { s[j] = no; j = j + i; } } }
            meow(n);
        }""", ()),
    "strings": ("""purr twice(s: str) -> str { bring s + s; }
        purr main() {
            yarn s = "ab" + "cd"; meow(s); meow(stretch(s)); meow(s[2]); meow(s == "abcd"); meow(s != "abcd"); meow("" + "");
            meow("Счёт: " + scribble(-12)); meow(stretch("мяу")); 
            yarn n = ["a", "b"]; n[0] = twice(n[1]); meow(n[0]);
            yarn t = ""; prowl i among 0..4 { t = t + scribble(i); } meow(t);
            yarn u = listen(); meow("Привет, " + u + "!");
            mew("no newline "); mew(u); meow("");
        }""", ("кот",)),
    "structs": ("""kit In { v: u8 } kit Out { name: str, ok: bool, arr: [u8], inner: In }
        kit Node { v: u32, next: Node }
        kit Sx { a: u8, b: i64 }
        purr add(a: P, b: P) -> P { bring P(a.x + b.x, a.y + b.y); }
        purr push(head: Node, v: u32) -> Node { bring Node(v, head); }
        purr sum(n: Node) -> u32 { yarn s: u32 = 0; chase n != ghost { s = s + n.v; n = n.next; } bring s; }
        purr main() {
            yarn p = P(3, -4); meow(p.x); p.y = p.x * 2; meow(p.y);
            yarn q = p; q.x = 99; meow(p.x); meow(p == q); meow(p == P(99, 6));
            yarn s = Sx(250, 7); s.a = s.a + 10; meow(s.a); meow(s.b);
            yarn o = Out("кот", yes, [5; 3], In(7)); meow(o.name); meow(o.ok); meow(o.arr[2]);
            o.inner.v = 8; meow(o.inner.v); o.name = o.name + "!"; meow(o.name);
            yarn r = add(P(1, 2), P(10, 20)); meow(r.x); meow(r.y);
            yarn h: Node = ghost; prowl i among 1 like u32..6 { h = push(h, i); } meow(sum(h)); meow(h.next.v);
            yarn a: [P] = [ghost, P(1, 2)]; meow(a[0] == ghost); meow(a[1] != ghost);
            yarn z: str = ghost; meow(z == ghost); z = "x"; meow(z == ghost); meow(z == "x");
        }""".replace("purr add", P + " purr add", 1), ()),
    "memory": ("""kit P { x: i32, y: i32 }
        purr main() {
            prowl i among 0..30000 { yarn p = P(1, 2); bury(p); }
            yarn a = [1; 100]; yarn s = "a" + "b"; bury(a); bury(s);
            bat32(8, 0xDEADBEEF); meow(look8(8)); meow(look16(10)); meow(look32(8));
            bat8(100, 255 like u8); meow(look8(100)); bat64(200, 18446744073709551615); meow(look64(200));
            meow(1);
        }""", ()),
}


@unittest.skipUnless(NODE, "Node.js не найден")
class HeapMatchesVM(unittest.TestCase):
    def test_cases(self):
        for name, (src, inputs) in NODE_CASES.items():
            if "listen" not in src:
                inputs = ()
            same(self, src, inputs)

    def test_gates_style_loop_with_arrays(self):
        src = """purr main() {
            yarn a = [0 like u32; 50]; prowl i among 0..stretch(a) { a[i] = i * i; }
            yarn t: u32 = 0; prowl i among 0..stretch(a) { t = t + a[i]; } meow(t);
        }"""
        same(self, src)


@unittest.skipUnless(NODE, "Node.js не найден")
class HeapTrapsMatchVM(unittest.TestCase):
    CASES = [
        ("yarn a = [1, 2]; yarn i: u32 = 2; meow(a[i]);", "out of bounds"),
        ("yarn a = [1, 2]; yarn i: u32 = 5; a[i] = 1;", "out of bounds"),
        ('meow("ab"[2 like u32]);', "out of bounds"),
        ("yarn a = [0 like u64; 4000000000 like u32]; meow(stretch(a));", "out of memory"),
        ('yarn s = "x"; chase yes { s = s + s; }', "out of memory"),
        ("yarn p = P(1, 2); bury(p); meow(p.x);", "invalid reference"),
        ("yarn a = [1, 2]; bury(a); a[0] = 5;", "invalid reference"),
        ("yarn p = P(1, 2); bury(p); bury(p);", "invalid reference"),
        ("yarn p = P(1, 2); bury(p); yarn q = P(5, 6); meow(q.x); meow(p.x);", "invalid reference"),
        ('yarn s = "const"; bury(s);', "constant"),
        ("yarn p: P = ghost; meow(p.x);", "invalid reference"),
        ("yarn a: [u8] = ghost; meow(stretch(a));", "invalid reference"),
        ("meow(look8(70000));", "out of bounds"),
        ("bat32(65534, 1);", "out of bounds"),
        ("yarn a = [1, 2]; a[5] = 1;", "out of bounds"),
    ]

    def test_same_trap(self):
        for body, phrase in self.CASES:
            src = f"{P}\npurr main() {{ meow(1); {body} }}"
            with self.assertRaises(CatTrap, msg=body) as c:
                run(src, native=True, max_steps=50_000_000)
            out, code, err = wasm_run(src)
            self.assertEqual(code, 3, (body, err))
            self.assertTrue(out.startswith("1\n"), body)
            self.assertIn(phrase, err, body)
            self.assertIn(phrase, c.exception.message, body)


if __name__ == "__main__":
    unittest.main()
