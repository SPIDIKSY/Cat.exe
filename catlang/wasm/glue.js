// Запуск .wasm-программы CAT: общий код для Node.js и браузера.
// io = { write(text), readLine() -> строка | null, seed }
class CatTrap extends Error {}

async function catRun(bytes, io) {
  const M = (1n << 64n) - 1n;
  let rng = (BigInt(io.seed || 0) & M) || 0x9E3779B97F4A7C15n;
  if (rng === 0n) rng = 1n;
  let inOk = true, mem = null, u8 = null, dv = null;
  const dec = new TextDecoder(), enc = new TextEncoder();
  const str = (p, n) => dec.decode(new Uint8Array(mem.buffer, p, n));

  // --- куча: те же правила, что в виртуальной машине (vm/vm.py) ---
  const USER_MEM = 65536, HEAP_END = 4 * 1024 * 1024;
  const K_ARRAY = 1, K_STR = 2, K_STRUCT = 3;
  let top = USER_MEM;
  const live = new Map(), gen = new Map(), freeLists = new Map(), pinned = new Set(), lits = new Map();
  function alloc(payload, kind, n) {
    const size = (8 + payload + 7) & ~7;
    const lst = freeLists.get(size);
    let addr;
    if (lst && lst.length) addr = lst.pop();
    else {
      if (top + size > HEAP_END) throw new CatTrap("out of memory");
      addr = top; top += size;
    }
    const g = ((gen.get(addr) || 0) % 8191) + 1;
    gen.set(addr, g); live.set(addr, size);
    dv.setUint32(addr, n, true); dv.setUint32(addr + 4, kind, true);
    return { h: ((g << 19) | (addr >> 3)) | 0, addr };
  }
  function obj(h, kinds) {
    h >>>= 0;
    const addr = (h & 0x7FFFF) << 3;
    if (!live.has(addr) || gen.get(addr) !== (h >>> 19)) throw new CatTrap("invalid reference (null, freed or forged)");
    if (kinds && !kinds.includes(u8[addr + 4])) throw new CatTrap("reference points to an object of a different kind");
    return addr;
  }
  const len = a => dv.getUint32(a, true);
  const newStr = bytes => {
    const { h, addr } = alloc(bytes.length, K_STR, bytes.length);
    u8.set(bytes, addr + 8);
    return h;
  };
  const text = h => { const a = obj(h, [K_STR]); return u8.slice(a + 8, a + 8 + len(a)); };
  const elemAddr = (h, i, es, write) => {
    const a = obj(h, write ? [K_ARRAY] : [K_ARRAY, K_STR]);
    const n = len(a);
    i >>>= 0;
    if (i >= n) throw new CatTrap(`index ${i} is out of bounds (length ${n})`);
    return a + 8 + i * es;
  };
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
    new_arr: (v, n, es) => {
      n >>>= 0;
      if (n * es + 8 > HEAP_END) throw new CatTrap("out of memory");
      const { h, addr } = alloc(n * es, K_ARRAY, n);
      v = BigInt.asUintN(64, v);
      if (es === 1) u8.fill(Number(v & 0xFFn), addr + 8, addr + 8 + n);
      else for (let i = 0; i < n; i++) for (let b = 0; b < es; b++) u8[addr + 8 + i * es + b] = Number((v >> BigInt(8 * b)) & 0xFFn);
      return h;
    },
    new_struct: size => { const { h, addr } = alloc(size, K_STRUCT, size); u8.fill(0, addr + 8, addr + 8 + size); return h; },
    aaddr_r: (h, i, es) => elemAddr(h, i, es, false),
    aaddr_w: (h, i, es) => elemAddr(h, i, es, true),
    faddr: (h, off, es) => {
      const a = obj(h, [K_STRUCT]);
      if (off + es > len(a)) throw new CatTrap("field is outside of the structure");
      return a + 8 + off;
    },
    alen: h => len(obj(h, [K_ARRAY, K_STR])),
    free: h => {
      const a = obj(h, null);
      if (pinned.has(a)) throw new CatTrap("cannot free a constant");
      const size = live.get(a);
      live.delete(a);
      if (!freeLists.has(size)) freeLists.set(size, []);
      freeLists.get(size).push(a);
    },
    str_lit: (p, n) => {
      const key = p + ":" + n;  // пустая строка и следующий литерал могут лежать по одному адресу
      if (!lits.has(key)) {
        const h = newStr(u8.slice(p, p + n));
        pinned.add(obj(h, null));
        lits.set(key, h);
      }
      return lits.get(key);
    },
    scat: (a, b) => { const x = text(a), y = text(b); const r = new Uint8Array(x.length + y.length); r.set(x); r.set(y, x.length); return newStr(r); },
    streq: (a, b) => { const x = text(a), y = text(b); return x.length === y.length && x.every((v, i) => v === y[i]) ? 1 : 0; },
    itos: (v, unsigned) => newStr(enc.encode((unsigned ? BigInt.asUintN(64, v) : v).toString())),
    reads: () => {
      const line = io.readLine();
      if (line === null) throw new CatTrap("end of input");
      return newStr(enc.encode(line));
    },
    print_v: h => io.write(dec.decode(text(h)) + "\n"),
    write_v: h => io.write(dec.decode(text(h))),
    uaddr: (a, n) => {
      a >>>= 0;
      if (a + n > USER_MEM) throw new CatTrap(`memory access out of bounds (address ${a})`);
      return a;
    },
  };
  const { instance } = await WebAssembly.instantiate(bytes, { env });
  mem = instance.exports.memory;
  u8 = new Uint8Array(mem.buffer);
  dv = new DataView(mem.buffer);
  const r = instance.exports.main();
  return r === undefined ? 0 : r & 0xFF;
}

if (typeof module !== "undefined") module.exports = { catRun, CatTrap };
