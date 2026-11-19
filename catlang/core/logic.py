"""Логическое ядро CAT.

Фундамент — четыре операции над одним битом, заданные ТАБЛИЦАМИ ИСТИННОСТИ:

    CAT  = AND   CATS = OR   MEOW = NOT   PAW = XOR

Всё остальное (сумматоры, вычитание, умножение, деление, сравнения, сдвиги)
ниже построено ТОЛЬКО из этих четырёх функций. Многобитное значение — список
битов, младший бит первым (little-endian).

Единственные места, где используются операции хоста — to_bits/from_bits:
это граница между «числом» и «списком битов», а не вычисление.
"""

# --- Таблицы истинности (единственное определение операций) ----------------
CAT_T = {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}
CATS_T = {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1}
PAW_T = {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}
MEOW_T = {0: 1, 1: 0}


def cat(a, b):
    return CAT_T[(a, b)]


def cats(a, b):
    return CATS_T[(a, b)]


def paw(a, b):
    return PAW_T[(a, b)]


def meow(a):
    return MEOW_T[a]


# --- Базовые схемы ---------------------------------------------------------
def mux(s, a, b):
    """Мультиплексор: s=0 -> a, s=1 -> b.   (NOT s AND a) OR (s AND b)"""
    return cats(cat(meow(s), a), cat(s, b))


def half_adder(a, b):
    """Полусумматор: (сумма, перенос) = (a PAW b, a CAT b)."""
    return paw(a, b), cat(a, b)


def full_adder(a, b, c):
    """Полный сумматор из двух полусумматоров и CATS."""
    s1, c1 = half_adder(a, b)
    s, c2 = half_adder(s1, c)
    return s, cats(c1, c2)


# --- Границы число <-> биты ------------------------------------------------
def to_bits(n, width):
    return [(n >> i) & 1 for i in range(width)]


def from_bits(bits):
    n = 0
    for i, b in enumerate(bits):
        n |= b << i
    return n


# --- Побитовые операции над словами ---------------------------------------
def w_cat(a, b):
    return [cat(x, y) for x, y in zip(a, b)]


def w_cats(a, b):
    return [cats(x, y) for x, y in zip(a, b)]


def w_paw(a, b):
    return [paw(x, y) for x, y in zip(a, b)]


def w_meow(a):
    return [meow(x) for x in a]


# --- Арифметика ------------------------------------------------------------
def add_bits(a, b, carry_in=0):
    """Сумматор со сквозным переносом. Возвращает (сумма, перенос_наружу)."""
    out, c = [], carry_in
    for x, y in zip(a, b):
        s, c = full_adder(x, y, c)
        out.append(s)
    return out, c


def sub_bits(a, b):
    """a - b = a + MEOW(b) + 1. Перенос наружу = 1  <=>  a >= b (без знака)."""
    return add_bits(a, w_meow(b), 1)


def neg_bits(a):
    """-a = MEOW(a) + 1 (дополнительный код)."""
    return add_bits(w_meow(a), [0] * len(a), 1)[0]


def mul_bits(a, b):
    """Умножение «сдвиг и сложение», результат усечён до ширины слов."""
    w = len(a)
    acc = [0] * w
    for i, bit in enumerate(b):
        shifted = [0] * i + a[: w - i]
        partial = [cat(bit, x) for x in shifted]
        acc, _ = add_bits(acc, partial)
    return acc


def udivmod_bits(a, b):
    """Деление без знака «с восстановлением». Делитель не должен быть нулём."""
    w = len(a)
    rem = [0] * (w + 1)
    bb = list(b) + [0]
    q = [0] * w
    for i in range(w - 1, -1, -1):
        rem = [a[i]] + rem[:-1]
        diff, ge = sub_bits(rem, bb)  # ge=1 <=> rem >= делитель
        rem = [mux(ge, r, d) for r, d in zip(rem, diff)]
        q[i] = ge
    return q, rem[:w]


def abs_bits(a):
    return [mux(a[-1], x, y) for x, y in zip(a, neg_bits(a))]


def sdivmod_bits(a, b):
    """Деление со знаком, округление к нулю; остаток со знаком делимого."""
    sa, sb = a[-1], b[-1]
    q, r = udivmod_bits(abs_bits(a), abs_bits(b))
    nq, nr = neg_bits(q), neg_bits(r)
    sq = paw(sa, sb)
    return [mux(sq, x, y) for x, y in zip(q, nq)], [mux(sa, x, y) for x, y in zip(r, nr)]


# --- Сравнения -------------------------------------------------------------
def eq_bits(a, b):
    diff = 0
    for x, y in zip(a, b):
        diff = cats(diff, paw(x, y))
    return meow(diff)


def ult_bits(a, b):
    """a < b без знака: при a - b нет переноса наружу."""
    return meow(sub_bits(a, b)[1])


def slt_bits(a, b):
    """a < b со знаком: инвертируем старшие биты и сравниваем как беззнаковые."""
    a2 = a[:-1] + [meow(a[-1])]
    b2 = b[:-1] + [meow(b[-1])]
    return ult_bits(a2, b2)


# --- Сдвиги (бочонковый сдвигатель из мультиплексоров) ---------------------
def shl_bits(a, amount):
    w = len(a)
    for k, s in enumerate(amount):
        n = 1 << k
        shifted = [0] * w if n >= w else [0] * n + a[: w - n]
        a = [mux(s, x, y) for x, y in zip(a, shifted)]
    return a


def shr_bits(a, amount, arithmetic=False):
    w = len(a)
    fill = a[-1] if arithmetic else 0
    for k, s in enumerate(amount):
        n = 1 << k
        shifted = [fill] * w if n >= w else a[n:] + [fill] * n
        a = [mux(s, x, y) for x, y in zip(a, shifted)]
    return a
