"""Дизассемблер байткода CAT."""
from ..core.cattypes import BY_CODE
from .opcodes import decode


def disassemble(p):
    ins = decode(p.code)
    starts = {f.entry: i for i, f in enumerate(p.funcs)}
    names = p.debug.names if p.debug else []
    lines = dict(p.debug.lines) if p.debug else {}
    out = [f"; CAT bytecode: {len(p.funcs)} function(s), {len(p.consts)} string(s), "
           f"{len(p.code)} byte(s) of code, {'with' if p.debug else 'no'} debug info"]
    for a, name, arg, ty in ins:
        if a in starts:
            i = starts[a]
            nm = names[i] if i < len(names) else f"fn#{i}"
            f = p.funcs[i]
            out.append(f"\n{nm}:   ; args={f.nargs} locals={f.nlocals}" + ("  <- entry" if i == p.entry else ""))
        parts = [f"{a:04X}  {name:<7}"]
        if ty is not None:
            parts.append(BY_CODE[ty].name)
        if arg is not None:
            if name == "CALL":
                parts.append(names[arg] if arg < len(names) else f"fn#{arg}")
            elif name in ("JMP", "JZ", "JNZ"):
                parts.append(f"{arg:04X}")
            elif name in ("PRINTS", "WRITES", "STR"):
                parts.append(repr(p.consts[arg]))
            else:
                parts.append(str(arg))
        text = " ".join(parts)
        if a in lines:
            text = f"{text:<34}; line {lines[a]}"
        out.append("  " + text)
    return "\n".join(out)
