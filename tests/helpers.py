from catlang.compiler.driver import compile_source
from catlang.core.alu import GateALU
from catlang.vm.vm import VM


def run(src, gates=False, strip=False, optimize=True, max_steps=2_000_000, inputs=(), seed=1):
    """Компилирует и выполняет; возвращает (вывод, код_выхода)."""
    out = []
    prog = compile_source(src, "t.cat", strip=strip, optimize_code=optimize)
    lines = iter(inputs)
    code = VM(prog, alu=GateALU() if gates else None, out=out.append, max_steps=max_steps,
              inp=lambda: next(lines, None), seed=seed).run()
    return "".join(out), code
