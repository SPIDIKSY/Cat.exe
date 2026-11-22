"""Структуры, ghost (пустая ссылка), bury (освобождение), защита кучи."""
import unittest

from catlang.compiler.diagnostics import CompileError
from catlang.compiler.driver import compile_source
from catlang.vm.opcodes import decode
from catlang.vm.vm import VM, CatTrap
from tests.helpers import run


def main(body, pre=""):
    return f"{pre}\npurr main() {{ {body} }}"


def out(src, **kw):
    return run(src, native=True, **kw)[0]


def trap(src):
    with __import__("unittest").TestCase().assertRaises(CatTrap) as c:
        run(src, native=True)
    return c.exception.message


class Structs(unittest.TestCase):
    P = "kit P { x: i32, y: i32 }"

    def test_construct_read_assign(self):
        self.assertEqual(out(main("yarn p = P(3, -4); meow(p.x); p.y = p.x * 2; meow(p.y);", self.P)), "3\n6\n")

    def test_field_types_wrap(self):
        src = main("yarn s = Sx(250, 7); s.a = s.a + 10; meow(s.a); meow(s.b);", "kit Sx { a: u8, b: i64 }")
        self.assertEqual(out(src), "4\n7\n")

    def test_references_shared(self):
        src = main("yarn p = P(1, 2); yarn q = p; q.x = 99; meow(p.x); meow(p == q); meow(p == P(99, 2));", self.P)
        self.assertEqual(out(src), "99\ntrue\nfalse\n")

    def test_fields_with_str_bool_array_struct(self):
        pre = "kit In { v: u8 } kit Out { name: str, ok: bool, arr: [u8], inner: In }"
        src = main('yarn o = Out("кот", yes, [5; 3], In(7)); meow(o.name); meow(o.ok); meow(o.arr[2]);'
                   ' o.inner.v = 8; meow(o.inner.v); o.name = o.name + "!"; meow(o.name);', pre)
        self.assertEqual(out(src), "кот\ntrue\n5\n8\nкот!\n")

    def test_struct_passed_and_returned(self):
        pre = self.P + " purr add(a: P, b: P) -> P { bring P(a.x + b.x, a.y + b.y); }"
        self.assertEqual(out(main("yarn r = add(P(1, 2), P(10, 20)); meow(r.x); meow(r.y);", pre)), "11\n22\n")

    def test_linked_list_with_ghost(self):
        pre = """kit Node { v: u32, next: Node }
        purr push(head: Node, v: u32) -> Node { bring Node(v, head); }
        purr sum(n: Node) -> u32 { yarn s: u32 = 0; chase n != ghost { s = s + n.v; n = n.next; } bring s; }"""
        src = main("yarn h: Node = ghost; prowl i among 1 like u32..6 { h = push(h, i); } meow(sum(h)); meow(h.next.v);", pre)
        self.assertEqual(out(src), "15\n4\n")

    def test_ghost_in_other_places(self):
        pre = self.P
        src = main("yarn a: [P] = [ghost, P(1, 2)]; meow(a[0] == ghost); meow(a[1] != ghost);"
                   ' yarn s: str = ghost; meow(s == ghost); s = "x"; meow(s == ghost); meow(s == "x");', pre)
        self.assertEqual(out(src), "true\ntrue\ntrue\nfalse\ntrue\n")

    def test_layout_alignment_and_size(self):
        p = compile_source("kit Sx { a: u8, b: u32, c: u8 } purr main() { yarn s = Sx(1, 2, 3); }", "t.cat")
        ins = decode(p.code)
        self.assertEqual([a for _, n, a, _ in ins if n == "NEWS"], [16])  # поля 0, 4, 8; итого 9 -> кратно 8
        offs = [a for _, n, a, _ in ins if n == "FSTORE"]
        self.assertEqual(offs, [0, 4, 8])

    def test_gate_mode_same(self):
        src = main("yarn p = P(3, 4); meow(p.x * p.y);", self.P)
        self.assertEqual(run(src, native=True), run(src, native=True, gates=True))


class Memory(unittest.TestCase):
    P = "kit P { x: i32, y: i32 }"

    def vm(self, src, inputs=()):
        p = compile_source(src, "t.cat")
        o = []
        vm = VM(p, out=o.append)
        return vm, o

    def test_bury_reuses_memory(self):
        # 200 000 выделений по ~16 байт без bury дали бы 3+ МиБ и упёрлись бы в лимит
        src = main("prowl i among 0..200000 { yarn p = P(1, 2); bury(p); } meow(1);", self.P).replace("purr", "purr")
        vm, o = self.vm(src)
        base = vm.live_bytes()
        vm.run()
        self.assertEqual("".join(o), "1\n")
        self.assertEqual(vm.live_bytes(), base)

    def test_without_bury_memory_runs_out(self):
        with self.assertRaises(CatTrap) as c:
            run(main("prowl i among 0..400000 { yarn p = P(1, 2); }", self.P), native=True, max_steps=50_000_000)
        self.assertIn("out of memory", c.exception.message)

    def test_arrays_and_strings_can_be_buried(self):
        vm, o = self.vm(main('yarn a = [1; 100]; yarn s = "a" + "b"; bury(a); bury(s); meow(0);'))
        base = vm.live_bytes()
        vm.run()
        self.assertEqual(vm.live_bytes(), base)

    def test_use_after_free(self):
        self.assertIn("freed", trap(main("yarn p = P(1, 2); bury(p); meow(p.x);", self.P)))
        self.assertIn("freed", trap(main("yarn a = [1, 2]; bury(a); a[0] = 5;")))
        self.assertIn("freed", trap(main("yarn s = \"a\" + \"b\"; bury(s); meow(s);")))

    def test_double_free(self):
        self.assertIn("invalid reference", trap(main("yarn p = P(1, 2); bury(p); bury(p);", self.P)))

    def test_stale_reference_after_reuse(self):
        # p освобождён, q занял то же место; старая ссылка p всё равно недействительна
        src = main("yarn p = P(1, 2); bury(p); yarn q = P(5, 6); meow(q.x); meow(p.x);", self.P)
        with self.assertRaises(CatTrap) as c:
            run(src, native=True)
        self.assertIn("invalid reference", c.exception.message)

    def test_constant_string_cannot_be_freed(self):
        self.assertIn("constant", trap(main('yarn s = "const"; bury(s);')))

    def test_null_dereference(self):
        self.assertIn("invalid reference", trap(main("yarn p: P = ghost; meow(p.x);", self.P)))
        self.assertIn("invalid reference", trap(main("yarn a: [u8] = ghost; meow(stretch(a));")))

    def test_forged_kind_rejected(self):
        # «подмена вида»: массив нельзя читать как структуру и наоборот
        vm = VM(compile_source(main("meow(0);"), "t.cat"))
        arr = vm.alloc(8, 1, 2, bytes(8))
        with self.assertRaises(CatTrap) as c:
            vm.field_addr(arr, 0, 4)
        self.assertIn("different kind", c.exception.message)
        st = vm.alloc(8, 3, 8, bytes(8))
        with self.assertRaises(CatTrap):
            vm.elem_addr(st, 0, 1)
        with self.assertRaises(CatTrap) as c:
            vm.field_addr(st, 6, 4)  # поле выходит за размер структуры
        self.assertIn("outside", c.exception.message)
        with self.assertRaises(CatTrap):
            vm.obj(12345, None)  # подделанное число


class Errors(unittest.TestCase):
    P = "kit P { x: i32, y: i32 }"

    def has(self, src, text):
        with self.assertRaises(CompileError) as c:
            compile_source(src, "t.cat")
        self.assertTrue(any(text in e.message for e in c.exception.errors), c.exception.render())

    def test_errors(self):
        self.has(main("yarn p = P(1, 2); meow(p.z);", self.P), "no field 'z'")
        self.has(main("yarn p = P(1); ", self.P), "got 1 value")
        self.has(main('yarn p = P(1, "a");', self.P), "type mismatch")
        self.has(main("yarn p = P(1, 2); p.x = yes;", self.P), "type mismatch")
        self.has(main("yarn x = 5; meow(x.y);"), "has no fields")
        self.has(main("yarn x = ghost;"), "cannot infer")
        self.has(main("yarn a = [ghost];"), "cannot infer")
        self.has(main("meow(ghost == ghost);"), "cannot")
        self.has(main("bury(5);"), "needs an array")
        self.has(main("yarn p: Q = ghost;"), "unknown type 'Q'")
        self.has("kit P { x: u8 } kit P { y: u8 } purr main() {}", "defined twice")
        self.has("kit P { x: u8, x: u8 } purr main() {}", "defined twice")
        self.has("kit u8 { x: u8 } purr main() {}", "built-in")
        self.has("kit P { x: u8 } purr P() {} purr main() {}", "already used")
        self.has(main("yarn p = P(1, 2); meow(p < p);", self.P), "cannot be applied")
        self.has(main("yarn p = P(1, 2); meow(p);", self.P), "cannot print")

    def test_module_call_still_works(self):
        self.assertEqual(out("adopt math; purr main() { yarn p = 12; meow(math.gcd(12, 18)); }"), "6\n")


if __name__ == "__main__":
    unittest.main()
