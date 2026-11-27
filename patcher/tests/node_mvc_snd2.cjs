/* Developer test: the MvC sound banks in Pyodide, one pass (sound_bank) vs the browser's three phases (sound_bank_plan ->
 * the ADPCM jobs with XVK.snd_encode, here in process -> sound_bank with the results): every output file's SHA-1 per bank.
 * PYODIDE_DIR=... node patcher/tests/node_mvc_snd2.cjs DISC.bin [BANK,BANK,...]   (bundle: patcher/xvsf_bundle.zip) */
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const XVK = require("../src/kernels.js"), MSK = require("../src/kernels_msh.js"), MVK = require("../src/kernels_mvc.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));
const ts = () => new Date().toISOString().slice(11, 19);
(async () => {
  const disc = path.resolve(process.argv[2]);
  const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR }); await py.loadPackage("numpy");
  py.unpackArchive(new Uint8Array(fs.readFileSync(path.join(__dirname, "..", "xvsf_bundle.zip"))), "zip", { extractDir: "/xvsf" });
  py.FS.mkdir("/in"); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(disc) }, "/in");
  py.runPython("import sys; sys.path.insert(0, '/xvsf/builder')");
  const vweb = py.pyimport("mvcb.web"); vweb.use_js_kernels(MVK.forPyodide(), MSK.forPyodide(), XVK.forPyodide());
  const games = py.pyimport("games"); const idn = JSON.parse(games.identify_web("/in/" + path.basename(disc)));
  let t = Date.now();
  const banks = JSON.parse(vweb.prepare("/in/" + path.basename(disc), "[]", idn.sha1, idn.size, () => {}, () => {}));
  console.log(ts(), "prepare %ss, %d banks", ((Date.now() - t) / 1000).toFixed(1), banks.length);
  const want = process.argv[3] ? process.argv[3].split(",") : banks.map((b) => b[0]);
  const clear = () => py.runPython("import mvcb.web as _w\nfor _c in _w._SND_MEMOS: _c.clear()");
  let bad = 0, T = { one: 0, plan: 0, enc: 0, two: 0 }, nj = 0;
  for (const bank of want) {
    const env = JSON.stringify(banks.find((b) => b[0] === bank)[1]);
    clear(); t = Date.now();
    const names1 = JSON.parse(vweb.sound_bank(bank, vweb.sound_src(bank), env)); const t1 = (Date.now() - t) / 1000;
    const h1 = {}; for (const n of names1) { const b = vweb.sound_file(n), u = b.toJs(); b.destroy(); h1[n] = crypto.createHash("sha1").update(u).digest("hex"); }
    clear(); t = Date.now();
    const plan = vweb.sound_bank_plan(bank, vweb.sound_src(bank), env);
    const meta = JSON.parse(plan.get(0)), arr = plan.get(1), buf = arr.getBuffer("i32"), inputs = buf.data.slice(); buf.release(); arr.destroy(); plan.destroy();
    const tp = (Date.now() - t) / 1000; t = Date.now();
    let tot = 0; for (const m of meta) tot += 16 * m[3];
    const res = new Uint8Array(tot); let o = 0;
    for (const m of meta) {
      const [nblk, s1, s2, K, M, B, R] = m.slice(3), out = new Uint8Array(16 * nblk);
      XVK.snd_encode(inputs.slice(m[1], m[1] + m[2]), nblk, s1, s2, K, M, B, R, out); res.set(out, o); o += out.length;
    }
    const te = (Date.now() - t) / 1000; t = Date.now();
    const names2 = JSON.parse(vweb.sound_bank(bank, vweb.sound_src(bank), env, JSON.stringify(meta), res)); const t2 = (Date.now() - t) / 1000;
    const h2 = {}; for (const n of names2) { const b = vweb.sound_file(n), u = b.toJs(); b.destroy(); h2[n] = crypto.createHash("sha1").update(u).digest("hex"); }
    const same = names1.length === names2.length && names1.every((k) => h1[k] === h2[k]);
    if (!same) bad++;
    T.one += t1; T.plan += tp; T.enc += te; T.two += t2; nj += meta.length;
    console.log(ts(), "bank %s: one pass %ss | plan %ss, %d jobs, encode %ss, pass 2 %ss | %d files %s", bank, t1.toFixed(1), tp.toFixed(1), meta.length, te.toFixed(1), t2.toFixed(1), names1.length, same ? "IDENTICAL" : "*** DIFFERENT ***");
  }
  console.log(ts(), "TOTAL one pass %ss | plan %ss, %d jobs, encode %ss, pass 2 %ss | %s", T.one.toFixed(1), T.plan.toFixed(1), nj, T.enc.toFixed(1), T.two.toFixed(1), bad ? bad + " BANKS DIFFERENT" : "ALL IDENTICAL");
  console.log("EXIT " + (bad ? 1 : 0));
})().catch((e) => { console.log(String(e && e.stack || e)); console.log("EXIT 2"); });
