"""АЛУ: два взаимозаменяемых исполнителя операций над значениями.

FastALU — быстрый (операции хоста). Используется по умолчанию.
GateALU — «честный»: каждая операция идёт через вентили CAT/CATS/MEOW/PAW
          из catlang.core.logic. Медленный, нужен для проверки.

Тесты доказывают, что оба дают одинаковые результаты.
Значения всегда в каноническом виде типа (см. cattypes.wrap).
Деление на ноль и неверные сдвиги отлавливает виртуальная машина ДО вызова АЛУ.
"""
from . import logic as L
from .cattypes import wrap


class FastALU:
    name = "fast"

    def cat(self, a, b, t): return a & b
    def cats(self, a, b, t): return a | b
    def paw(self, a, b, t): return a ^ b
    def meow(self, a, t): return wrap(~a, t)
    def add(self, a, b, t): return wrap(a + b, t)
    def sub(self, a, b, t): return wrap(a - b, t)
    def mul(self, a, b, t): return wrap(a * b, t)
    def neg(self, a, t): return wrap(-a, t)

    def _q(self, a, b):
        q = abs(a) // abs(b)
        return -q if (a < 0) != (b < 0) else q

    def div(self, a, b, t): return wrap(self._q(a, b), t)
    def rem(self, a, b, t): return wrap(a - self._q(a, b) * b, t)
    def shl(self, a, b, t): return wrap(a << b, t)
    def shr(self, a, b, t): return a >> b
    def eq(self, a, b, t): return int(a == b)
    def ne(self, a, b, t): return int(a != b)
    def lt(self, a, b, t): return int(a < b)
    def le(self, a, b, t): return int(a <= b)
    def gt(self, a, b, t): return int(a > b)
    def ge(self, a, b, t): return int(a >= b)
    def cast(self, a, t): return wrap(a, t)


class GateALU:
    name = "gates"

    @staticmethod
    def _in(v, t):
        return L.to_bits(v & t.mask, t.bits)

    @staticmethod
    def _out(bits, t):
        return wrap(L.from_bits(bits), t)

    def _bin(self, f, a, b, t):
        return self._out(f(self._in(a, t), self._in(b, t)), t)

    def cat(self, a, b, t): return self._bin(L.w_cat, a, b, t)
    def cats(self, a, b, t): return self._bin(L.w_cats, a, b, t)
    def paw(self, a, b, t): return self._bin(L.w_paw, a, b, t)
    def meow(self, a, t): return self._out(L.w_meow(self._in(a, t)), t)
    def add(self, a, b, t): return self._bin(lambda x, y: L.add_bits(x, y)[0], a, b, t)
    def sub(self, a, b, t): return self._bin(lambda x, y: L.sub_bits(x, y)[0], a, b, t)
    def mul(self, a, b, t): return self._bin(L.mul_bits, a, b, t)
    def neg(self, a, t): return self._out(L.neg_bits(self._in(a, t)), t)

    def div(self, a, b, t):
        f = L.sdivmod_bits if t.signed else L.udivmod_bits
        return self._out(f(self._in(a, t), self._in(b, t))[0], t)

    def rem(self, a, b, t):
        f = L.sdivmod_bits if t.signed else L.udivmod_bits
        return self._out(f(self._in(a, t), self._in(b, t))[1], t)

    def shl(self, a, b, t):
        return self._out(L.shl_bits(self._in(a, t), self._in(b, t)), t)

    def shr(self, a, b, t):
        return self._out(L.shr_bits(self._in(a, t), self._in(b, t), t.signed), t)

    def _lt(self, a, b, t):
        f = L.slt_bits if t.signed else L.ult_bits
        return f(self._in(a, t), self._in(b, t))

    def eq(self, a, b, t): return L.eq_bits(self._in(a, t), self._in(b, t))
    def ne(self, a, b, t): return L.meow(self.eq(a, b, t))
    def lt(self, a, b, t): return self._lt(a, b, t)
    def gt(self, a, b, t): return self._lt(b, a, t)
    def le(self, a, b, t): return L.meow(self._lt(b, a, t))
    def ge(self, a, b, t): return L.meow(self._lt(a, b, t))
    def cast(self, a, t): return self._out(self._in(a, t), t)
