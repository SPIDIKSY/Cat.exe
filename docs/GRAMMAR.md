# Грамматика CAT (EBNF)

Комментарии: `// до конца строки`. Пробелы и переводы строк не значимы.

```ebnf
program   = { use | func } ;
use       = "use" ident ";" ;
func      = "fn" ident "(" [ param { "," param } ] ")" [ "->" type ] block ;
param     = ident ":" type ;
type      = "bool" | "u8" | "u16" | "u32" | "u64" | "i8" | "i16" | "i32" | "i64" ;

block     = "{" { stmt } "}" ;
stmt      = "let" ident [ ":" type ] "=" expr ";"
          | ident "=" expr ";"
          | "if" expr block [ "else" ( if_stmt | block ) ]
          | "while" expr block
          | "return" [ expr ] ";"
          | block
          | expr ";" ;

expr      = or ;                        (* уровни от слабого к сильному *)
or        = xor   { "cats" xor } ;
xor       = and   { "paw"  and } ;
and       = equal { "cat"  equal } ;
equal     = order { ("==" | "!=") order } ;
order     = shift { ("<" | "<=" | ">" | ">=") shift } ;
shift     = sum   { ("<<" | ">>") sum } ;
sum       = term  { ("+" | "-") term } ;
term      = cast  { ("*" | "/" | "%") cast } ;
cast      = unary { "as" type } ;
unary     = "meow" unary | "-" unary | primary ;
primary   = int | string | "true" | "false" | "(" expr ")"
          | ident [ "." ident ] "(" [ expr { "," expr } ] ")"   (* вызов *)
          | ident ;

int       = dec | "0x" hex | "0b" bin ;  (* допускается "_": 1_000_000 *)
string    = '"' { char | "\n" | "\t" | "\\" | "\"" | "\0" } '"' ;
ident     = (letter | "_") { letter | digit | "_" } ;
```

Ключевые слова: `fn let if else while return as true false use cat cats meow paw`.
Встроенные функции: `print assert peek8 peek16 peek32 peek64 poke8 poke16 poke32 poke64`.

Правила типов: оба операнда бинарной операции одного типа; условия — `bool`;
`<` `<=` `>` `>=` — только для целых; `-` (унарный) — только для знаковых;
строки — только аргумент `print`; `main` — без параметров, возвращает ничего или `i32`.
