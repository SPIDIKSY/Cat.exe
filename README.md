# CAT

Низкоуровневый язык с логическим ядром из четырёх операций:
**`cat`** (И), **`cats`** (ИЛИ), **`meow`** (НЕ), **`paw`** (исключающее ИЛИ).
Сложение, вычитание, умножение, деление, сравнения и сдвиги построены только из них
(`catlang/core/logic.py`) и проверены тестами против быстрого исполнения.

Статус: **прототип (этап 1)** — `.cat` → компилятор → байткод `.catc` → собственная VM. Подробнее: [docs/DESIGN.md](docs/DESIGN.md).

## Запуск (нужен Python 3.10+, больше ничего)

Из папки проекта (Windows PowerShell или Linux):

```
python -m catlang run examples/hello.cat          # выполнить
python -m catlang run examples/gates.cat --gates  # всё считать через вентили
python -m catlang build examples/fib.cat          # -> examples/fib.catc
python -m catlang build examples/fib.cat --strip  # релиз без отладочной информации
python -m catlang run examples/fib.catc
python -m catlang disasm examples/fib.cat         # посмотреть байткод
python -m catlang run examples/guess.cat           # игра «Угадай число»
python -m catlang logic                           # таблицы истинности + самопроверка
python -m unittest discover -t . -s tests         # тесты
```
В Windows можно короче: `.\cat.cmd run examples\hello.cat`.

## Пример

```
fn main() {
    let x: u8 = 0b1100;
    let y: u8 = 0b1010;
    print(x cat y);    // 8
    print(x cats y);   // 14
    print(x paw y);    // 6
    print(meow x);     // 243
}
```
Документы: [DESIGN](docs/DESIGN.md) · [GRAMMAR](docs/GRAMMAR.md) · [BYTECODE](docs/BYTECODE.md).
