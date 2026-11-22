// Запуск .wasm, собранного командой `python -m catlang wasm`:  node tools/run_wasm.js prog.wasm [--seed N]
const fs = require("fs");
const { catRun, CatTrap } = require("../catlang/wasm/glue.js");

const args = process.argv.slice(2);
const file = args.find(a => !a.startsWith("--") && args[args.indexOf(a) - 1] !== "--seed");
const si = args.indexOf("--seed");
const seed = si >= 0 ? BigInt(args[si + 1]) : BigInt(Math.floor(Math.random() * 2 ** 52) + 1);
let lines = null;
const readLine = () => {
  if (lines === null) {
    try { lines = fs.readFileSync(0, "utf8").split("\n"); if (lines[lines.length - 1] === "") lines.pop(); }
    catch (e) { lines = []; }
  }
  return lines.length ? lines.shift().replace(/\r$/, "") : null;
};

catRun(fs.readFileSync(file), { write: s => process.stdout.write(s), readLine, seed })
  .then(code => process.exit(code))
  .catch(e => {
    const msg = e instanceof CatTrap ? e.message
      : e instanceof WebAssembly.RuntimeError ? ({ "divide by zero": "division by zero", "remainder by zero": "division by zero", unreachable: "assertion failed or invalid shift" }[e.message] || e.message)
      : e.stack;
    process.stderr.write(`runtime error: ${msg}\n`);
    process.exit(3);
  });
