# Грамматика CAT (EBNF)

Комментарии: `// до конца строки`. Пробелы и переводы строк не значимы.

```ebnf
program   = { use | func } ;
use       = "adopt" ident ";" ;
func      = "purr" ident "(" [ param { "," param } ] ")" [ "->" type ] block ;
param     = ident ":" type ;
type      = "bool" | "u8" | "u16" | "u32" | "u64" | "i8" | "i16" | "i32" | "i64" ;

block     = "{" { stmt } "}" ;
stmt      = "yarn" ident [ ":" type ] "=" expr ";"
          | ident "=" expr ";"
          | "sniff" expr block [ "hiss" ( if_stmt | block ) ]
          | "chase" expr block
          | "prowl" ident "among" expr ".." expr block   (* i = начало .. конец-1 *)
          | "scat" ";" | "hop" ";"
          | "bring" [ expr ] ";"
          | block
          | expr ";" ;

expr      = lor ;                       (* уровни от слабого к сильному *)
lor       = land  { "||" land } ;       (* только bool, короткое вычисление *)
land      = or    { "&&" or } ;
or        = xor   { "A" xor } ;
xor       = and   { "S"  and } ;
and       = equal { "C"  equal } ;
equal     = order { ("==" | "!=") order } ;
order     = shift { ("<" | "<=" | ">" | ">=") shift } ;
shift     = sum   { ("<<" | ">>") sum } ;
sum       = term  { ("+" | "-") term } ;
term      = cast  { ("*" | "/" | "%") cast } ;
cast      = unary { "like" type } ;
unary     = "T" unary | "-" unary | primary ;
primary   = int | string | "yes" | "no" | "(" expr ")"
          | ident [ "." ident ] "(" [ expr { "," expr } ] ")"   (* вызов *)
          | ident ;

int       = dec | "0x" hex | "0b" bin ;  (* допускается "_": 1_000_000 *)
string    = '"' { char | "\n" | "\t" | "\\" | "\"" | "\0" } '"' ;
ident     = (letter | "_") { letter | digit | "_" } ;
```

## Слова языка (всё кошачье)

| Слово | Значит | | Слово | Значит |
|---|---|---|---|---|
| `purr` | `fn` — функция | | `yes` / `no` | `true` / `false` |
| `yarn` | `let` — переменная | | `adopt` | `use` — подключить модуль |
| `sniff` / `hiss` | `if` / `else` | | **`C`** | **И** (AND) |
| `chase` | `while` | | **`A`** | **ИЛИ** (OR) |
| `prowl … among` | `for … in` | | **`T`** | **НЕ** (NOT) |
| `scat` / `hop` | `break` / `continue` | | **`S`** | **исключающее ИЛИ** (XOR) |
| `bring` | `return` | | `like` | `as` — приведение типа |

Сердце языка — четыре **заглавные** буквы `C A T S` (одна буква — один оператор; поэтому имена `C`, `A`, `T`, `S`
заняты). Типы: `bool u8 u16 u32 u64 i8 i16 i32 i64`.

Встроенные функции: `meow(x)` печать со строкой · `mew(x)` печать без переноса · `claw(cond)` проверка ·
`ask()` ввод числа · `heard()` «число введено?» · `roll(n)` случайное 0..n-1 ·
`look8/16/32/64(addr)` чтение памяти · `bat8/16/32/64(addr, v)` запись в память.
Прежние английские слова (`fn`, `print`, `cat` …) ничего не значат — это обычные имена.
Все слова задаёт один файл: `catlang/compiler/vocab.py`.

Правила типов: оба операнда бинарной операции одного типа; условия — `bool`;
`<` `<=` `>` `>=` — только для целых; `-` (унарный) — только для знаковых;
строки — только аргумент `print`; `main` — без параметров, возвращает ничего или `i32`.
