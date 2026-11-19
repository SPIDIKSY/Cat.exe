from catlang.compiler import driver
from tests.legacy import convert
from catlang.core.alu import GateALU
from catlang.vm.vm import VM


def compile_source(src, *a, native=False, **kw):
    """Тесты написаны старыми английскими словами; переводим их в кошачьи перед компиляцией.
    native=True — исходник уже на кошачьих словах (файлы из examples/)."""
    return driver.compile_source(src if native else convert(src), *a, **kw)


def run(src, gates=False, strip=False, optimize=True, max_steps=2_000_000, inputs=(), seed=1, native=False):
    """Компилирует и выполняет; возвращает (вывод, код_выхода)."""
    out = []
    prog = compile_source(src, "t.cat", strip=strip, optimize_code=optimize, native=native)
    lines = iter(inputs)
    code = VM(prog, alu=GateALU() if gates else None, out=out.append, max_steps=max_steps,
              inp=lambda: next(lines, None), seed=seed).run()
    return "".join(out), code
