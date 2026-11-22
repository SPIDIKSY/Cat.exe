"""Конвейер компиляции: исходник -> токены -> AST -> проверка -> оптимизация -> байткод."""
from ..platform import host
from . import ast as A
from .checker import Checker
from .codegen import generate
from .diagnostics import CatError, CompileError
from .optimizer import optimize
from .parser import parse


def load_modules(prog, sources, file, extra=()):
    """Подключает `use name;` из stdlib/. Функции модуля получают имя `module.func`."""
    funcs, structs = list(prog.funcs), list(prog.structs)
    loaded = set()

    def load(uses, in_file):
        for u in uses:
            if u.name in loaded:
                continue
            path = host.stdlib_path(u.name)
            if not host.exists(path):
                raise CompileError([CatError(f"unknown module '{u.name}'", u.line, u.col, in_file)], sources)
            loaded.add(u.name)
            text = host.read_text(path)
            sources[path] = text
            try:
                mod = parse(text, path)
            except CatError as e:
                raise CompileError([e], sources)
            structs.extend(mod.structs)
            for f in mod.funcs:
                f.module, f.name = u.name, f"{u.name}.{f.name}"
                funcs.append(f)
            load(mod.uses, path)

    load(list(prog.uses) + [A.Use(1, 1, m) for m in extra], file)
    return funcs, structs


def frontend(text, filename, optimize_code=True, extra_modules=()):
    """Разбор, проверка типов, оптимизация. Возвращает (функции, исходники)."""
    sources = {filename: text}
    try:
        prog = parse(text, filename)
    except CatError as e:
        raise CompileError([e], sources)
    funcs, structs = load_modules(prog, sources, filename, extra_modules)
    Checker(funcs, sources, structs).run()
    if optimize_code:
        optimize(funcs)
    return funcs, sources


def compile_source(text, filename="<input>", strip=False, optimize_code=True):
    """Возвращает vm.format.Program. При ошибках бросает CompileError."""
    funcs, _ = frontend(text, filename, optimize_code)
    return generate(funcs, strip=strip, file=filename)


def compile_native_source(text, filename="<input>", target="linux", seed=None):
    """Возвращает байты исполняемого файла для target: linux (ELF), windows (PE), macos (Mach-O, Intel)."""
    from ..native.codegen import generate_native
    from ..native.formats import MAKERS
    funcs, sources = frontend(text, filename, extra_modules=("rt",))
    try:
        asm, _ = generate_native(funcs, target, seed)
    except CompileError as e:
        e.sources = sources
        raise
    return MAKERS[target](asm)


def compile_wasm_source(text, filename="<input>"):
    """Возвращает (байты .wasm, main_возвращает_i32)."""
    from ..wasm.backend import compile_wasm
    funcs, sources = frontend(text, filename)
    try:
        return compile_wasm(funcs)
    except CompileError as e:
        e.sources = sources
        raise


def compile_file(path, strip=False, optimize_code=True):
    return compile_source(host.read_text(path), path, strip, optimize_code)
