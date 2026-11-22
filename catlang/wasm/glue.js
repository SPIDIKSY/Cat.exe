// Запуск .wasm-программы CAT: общий код для Node.js и браузера.
// io = { write(text), readLine() -> строка | null, seed }
class CatTrap extends Error {}

async function catRun(bytes, io) {
  const M = (1n << 64n) - 1n;
  let rng = (BigInt(io.seed || 0) & M) || 0x9E3779B97F4A7C15n;
  if (rng === 0n) rng = 1n;
  let inOk = true, mem = null;
  const dec = new TextDecoder();
  const str = (p, n) => dec.decode(new Uint8Array(mem.buffer, p, n));
  const env = {
    print_i64: v => io.write(v.toString() + "\n"),
    write_i64: v => io.write(v.toString()),
    print_u64: v => io.write(BigInt.asUintN(64, v).toString() + "\n"),
    write_u64: v => io.write(BigInt.asUintN(64, v).toString()),
    print_bool: v => io.write(v ? "true\n" : "false\n"),
    write_bool: v => io.write(v ? "true" : "false"),
    print_str: (p, n) => io.write(str(p, n) + "\n"),
    write_str: (p, n) => io.write(str(p, n)),
    roll: n => {  // xorshift64 — тот же генератор, что и в виртуальной машине
      n = n >>> 0;
      if (n === 0) throw new CatTrap("rand(0): range is empty");
      let x = rng;
      x ^= (x << 13n) & M; x ^= x >> 7n; x ^= (x << 17n) & M;
      rng = x;
      return Number(x % BigInt(n)) | 0;
    },
    ask: () => {
      const line = io.readLine();
      if (line === null) throw new CatTrap("end of input");
      const t = line.trim();
      if (/^[+-]?[0-9]+$/.test(t)) {
        const v = BigInt(t);
        if (v >= -(1n << 63n) && v < (1n << 63n)) { inOk = true; return v; }
      }
      inOk = false;
      return 0n;
    },
    heard: () => (inOk ? 1 : 0),
  };
  const { instance } = await WebAssembly.instantiate(bytes, { env });
  mem = instance.exports.memory;
  const r = instance.exports.main();
  return r === undefined ? 0 : r & 0xFF;
}

if (typeof module !== "undefined") module.exports = { catRun, CatTrap };
