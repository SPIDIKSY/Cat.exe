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
purr main() {
    yarn x: u8 = 0b1100;
    yarn y: u8 = 0b1010;
    meow(x C y);    // И          = 8
    meow(x A y);    // ИЛИ        = 14
    meow(x S y);    // искл. ИЛИ  = 6
    meow(T x);      // НЕ         = 243
}
```
Слова языка — кошачьи (`purr` функция, `yarn` переменная, `sniff` если, `chase` пока, `meow` печать…),
четыре логические операции — буквы `C A T S`. Полная таблица: [docs/GRAMMAR.md](docs/GRAMMAR.md).

Документы: [DESIGN](docs/DESIGN.md) · [GRAMMAR](docs/GRAMMAR.md) · [BYTECODE](docs/BYTECODE.md).
