"""Командная строка CAT:  python -m catlang <команда> ..."""
import argparse

from . import __version__
from .compiler.diagnostics import CompileError
from .compiler.driver import compile_file, compile_wasm_source
from .compiler.formatter import format_source
from .core import logic as L
from .core.alu import GateALU
from .platform import host
from .vm import format as fmt
from .vm.disasm import disassemble
from .vm.vm import VM, CatTrap

EXIT_COMPILE, EXIT_USAGE, EXIT_TRAP = 1, 2, 3


def load(path, strip=False):
    """Принимает исходник .cat или байткод .catc."""
    if path.endswith(".catc"):
        return fmt.from_bytes(host.read_bytes(path))
    return compile_file(path, strip=strip)


def cmd_run(a):
    prog = load(a.file)
    seed = a.seed if a.seed is not None else host.random_seed()
    vm = VM(prog, alu=GateALU() if a.gates else None, out=host.write_out,
            max_steps=a.max_steps, inp=host.read_line, seed=seed)
    try:
        return vm.run()
    except CatTrap as e:
        host.write_err(f"runtime error: {e.message}\n  {e.where}\n")
        return EXIT_TRAP


def cmd_build(a):
    prog = compile_file(a.file, strip=a.strip)
    out = a.output or (a.file[:-4] if a.file.endswith(".cat") else a.file) + ".catc"
    data = fmt.to_bytes(prog)
    host.write_bytes(out, data)
    host.write_out(f"{out}: {len(data)} bytes ({'stripped' if a.strip else 'with debug info'})\n")
    return 0


HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAT: %(title)s</title>
<style>body{font:16px/1.4 system-ui,sans-serif;margin:16px;background:#fff;color:#111}
pre{background:#f4f4f4;padding:12px;border-radius:8px;white-space:pre-wrap}
@media(prefers-color-scheme:dark){body{background:#161616;color:#eee}pre{background:#252525}}</style></head>
<body><h1>CAT: %(title)s</h1><pre id="out"></pre>
<script>
%(glue)s
const bytes = Uint8Array.from(atob("%(b64)s"), c => c.charCodeAt(0));
const out = document.getElementById("out");
catRun(bytes, { write: s => { out.textContent += s; },
  readLine: () => { const v = prompt("Ввод (отмена = конец ввода):"); return v === null ? null : v; },
  seed: BigInt(Math.floor(Math.random() * 2 ** 52) + 1) })
  .then(c => { out.textContent += "\\n[программа завершена, код " + c + "]"; })
  .catch(e => { out.textContent += "\\nruntime error: " + e.message; });
</script></body></html>
"""


def cmd_wasm(a):
    import base64
    import os
    wasm, _ = compile_wasm_source(host.read_text(a.file), a.file)
    base = a.output or (a.file[:-4] if a.file.endswith(".cat") else a.file) + ".wasm"
    host.write_bytes(base, wasm)
    host.write_out(f"{base}: {len(wasm)} bytes (WebAssembly)\n")
    if a.html:
        glue = host.read_text(os.path.join(os.path.dirname(__file__), "wasm", "glue.js"))
        page = HTML % {"title": os.path.basename(a.file), "glue": glue, "b64": base64.b64encode(wasm).decode()}
        html = base[:-5] + ".html" if base.endswith(".wasm") else base + ".html"
        host.write_bytes(html, page.encode("utf-8"))
        host.write_out(f"{html}: страница для браузера\n")
    return 0


def cmd_check(a):
    compile_file(a.file)
    if a.json:
        host.write_out('{"ok": true, "errors": []}\n')
    else:
        host.write_out(f"{a.file}: ok\n")
    return 0


def cmd_fmt(a):
    old = host.read_text(a.file)
    new = format_source(old)
    if a.check:
        if new != old:
            host.write_err(f"{a.file}: needs formatting\n")
            return 1
        return 0
    if new != old:
        host.write_bytes(a.file, new.encode("utf-8"))
        host.write_out(f"{a.file}: formatted\n")
    return 0


def cmd_disasm(a):
    host.write_out(disassemble(load(a.file)) + "\n")
    return 0


def cmd_logic(a):
    host.write_out("Таблицы истинности CAT (1 = истина):\n")
    host.write_out(" a b | CAT CATS PAW      a | MEOW\n")
    for x in (0, 1):
        for y in (0, 1):
            host.write_out(f" {x} {y} |  {L.cat(x, y)}   {L.cats(x, y)}    {L.paw(x, y)}      "
                           + (f"{x} |  {L.meow(x)}" if y == 0 else "") + "\n")
    host.write_out("\nСумматор: 1 + 1 + 1 (перенос) -> сумма,перенос = %s\n" % (L.full_adder(1, 1, 1),))
    host.write_out("Проверка: 8-битные операции через вентили и быстрое АЛУ...\n")
    from .core.alu import FastALU
    from .core.cattypes import I8, U8, wrap
    fast, gate, bad, n = FastALU(), GateALU(), 0, 0
    for t in (U8, I8):
        for x in range(256):
            x = wrap(x, t)
            for y in (0, 1, 2, 3, 7, 100, 127, 128, 255):
                y = wrap(y, t)
                for op in ("cat", "cats", "paw", "add", "sub", "mul", "eq", "lt", "ge"):
                    n += 1
                    if getattr(fast, op)(x, y, t) != getattr(gate, op)(x, y, t):
                        bad += 1
    host.write_out(f"OK: {n} проверок, вентили и быстрое АЛУ совпадают\n" if not bad
                   else f"ОШИБКА: {bad} расхождений из {n}\n")
    return 1 if bad else 0


def main(argv=None):
    host.setup_console()
    ap = argparse.ArgumentParser(prog="cat", description="CAT — язык с логическим ядром CAT/CATS/MEOW/PAW")
    ap.add_argument("--version", action="version", version=f"CAT {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="выполнить .cat или .catc")
    r.add_argument("file")
    r.add_argument("--gates", action="store_true", help="считать через вентили (медленно, для проверки)")
    r.add_argument("--max-steps", type=int, default=None, help="лимит инструкций")
    r.add_argument("--seed", type=int, default=None, help="начальное число для rand() (для повторяемости)")
    b = sub.add_parser("build", help="скомпилировать .cat в .catc")
    b.add_argument("file")
    b.add_argument("-o", "--output")
    b.add_argument("--strip", action="store_true", help="без отладочной информации (релиз)")
    c = sub.add_parser("check", help="только проверить программу (без запуска)")
    c.add_argument("file")
    f = sub.add_parser("fmt", help="привести код к единому виду")
    f.add_argument("file")
    f.add_argument("--check", action="store_true", help="не менять файл, только проверить")
    for p in (r, b, c):
        p.add_argument("--json", action="store_true", help="ошибки компиляции в формате JSON (для программ и ИИ)")
    w = sub.add_parser("wasm", help="скомпилировать в WebAssembly (.wasm)")
    w.add_argument("file")
    w.add_argument("-o", "--output")
    w.add_argument("--html", action="store_true", help="ещё и готовая страница для браузера")
    w.add_argument("--json", action="store_true", help="ошибки компиляции в формате JSON")
    d = sub.add_parser("disasm", help="показать байткод")
    d.add_argument("file")
    sub.add_parser("logic", help="таблицы истинности и самопроверка логического ядра")
    a = ap.parse_args(argv)
    fn = {"run": cmd_run, "build": cmd_build, "check": cmd_check, "fmt": cmd_fmt, "wasm": cmd_wasm,
          "disasm": cmd_disasm, "logic": cmd_logic}[a.cmd]
    try:
        return fn(a)
    except CompileError as e:
        host.write_err((e.to_json() if getattr(a, "json", False) else e.render()) + "\n")
        return EXIT_COMPILE
    except fmt.FormatError as e:
        host.write_err(f"bad bytecode file: {e}\n")
        return EXIT_USAGE
    except OSError as e:
        host.write_err(f"file error: {e}\n")
        return EXIT_USAGE
