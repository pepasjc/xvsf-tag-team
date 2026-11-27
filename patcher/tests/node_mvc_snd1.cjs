/* Developer test: one MvC sound bank in Pyodide, unpatched vs patched (builder/mvcb/web.py _patch_sound): time + every
 * output file's SHA-1.  PYODIDE_DIR=... node patcher/tests/node_mvc_snd1.cjs DISC.bin [BANK]   (bundle: patcher/xvsf_bundle.zip) */
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const XVK = require("../src/kernels.js"), MSK = require("../src/kernels_msh.js"), MVK = require("../src/kernels_mvc.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));
(async () => {
  const disc = path.resolve(process.argv[2]), bank = process.argv[3] || "01";
  async function run(patch) {
    const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR }); await py.loadPackage("numpy");
    py.unpackArchive(new Uint8Array(fs.readFileSync(path.join(__dirname, "..", "xvsf_bundle.zip"))), "zip", { extractDir: "/xvsf" });
    py.FS.mkdir("/in"); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(disc) }, "/in");
    py.runPython("import sys, os; sys.path.insert(0, '/xvsf/builder'); os.environ['MVCB_NOSNDPATCH'] = '" + (patch ? "0" : "1") + "'");
    const vweb = py.pyimport("mvcb.web"); vweb.use_js_kernels(MVK.forPyodide(), MSK.forPyodide(), XVK.forPyodide());
    const games = py.pyimport("games"); const idn = JSON.parse(games.identify_web("/in/" + path.basename(disc)));
    let t = Date.now();
    const banks = JSON.parse(vweb.prepare("/in/" + path.basename(disc), "[]", idn.sha1, idn.size, () => {}, () => {}));
    const tp = (Date.now() - t) / 1000; const env = banks.find((b) => b[0] === bank)[1];
    const src = vweb.sound_src(bank); t = Date.now();
    const names = JSON.parse(vweb.sound_bank(bank, src, JSON.stringify(env))); const ts = (Date.now() - t) / 1000;
    const h = {}; for (const n of names) { const b = vweb.sound_file(n), u = b.toJs(); b.destroy(); h[n] = crypto.createHash("sha1").update(u).digest("hex"); }
    return { tp, ts, h };
  }
  const a = await run(false), b = await run(true);
  const same = Object.keys(a.h).length === Object.keys(b.h).length && Object.keys(a.h).every((k) => a.h[k] === b.h[k]);
  console.log("bank %s: prepare %ss | unpatched %ss | patched %ss | %d files %s", bank, a.tp.toFixed(1), a.ts.toFixed(1), b.ts.toFixed(1), Object.keys(a.h).length, same ? "IDENTICAL" : "*** DIFFERENT ***");
})();
