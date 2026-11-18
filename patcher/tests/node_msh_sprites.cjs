/* Developer check: the MSHvSF sprite encoders (builder/mshb) inside Pyodide under Node, with the JavaScript kernels
 * (patcher/src/kernels_msh.js + kernels.js), against the reference files in games/mshvsf/work/dsp/<tier>/.
 * Prints the time of every job and an estimate for all jobs of a build.
 *
 *   npm i pyodide@0.25.1            (anywhere; pass that folder's node_modules/pyodide as PYODIDE_DIR)
 *   PYODIDE_DIR=.../node_modules/pyodide node patcher/tests/node_msh_sprites.cjs [XX ...|all] [--tier T ...] [--noverify]
 *   (default characters: 01 0B 10, all 9 tiers)
 */
const fs = require("fs"), path = require("path");
const XVK = require("../src/kernels.js");
const MSK = require("../src/kernels_msh.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));
const ROOT = path.join(__dirname, "..", "..");
const REF = path.join(ROOT, "games", "mshvsf", "work", "dsp");

(async () => {
  const args = process.argv.slice(2);
  const ti = args.indexOf("--tier");
  const tiers = ti >= 0 ? args.slice(ti + 1).filter((a) => !a.startsWith("--")) : null;
  const pos = (ti >= 0 ? args.slice(0, ti) : args).filter((a) => !a.startsWith("--"));
  const verify = !args.includes("--noverify");
  const t0 = Date.now();
  const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR });
  await py.loadPackage("numpy");
  // the Python sources and data the encoders need, copied into the in-memory file system
  const put = (rel) => {
    const dst = "/msh/" + rel.replace(/\\/g, "/");
    py.FS.mkdirTree(path.posix.dirname(dst));
    py.FS.writeFile(dst, fs.readFileSync(path.join(ROOT, rel)));
  };
  for (const f of ["__init__", "kernels", "huff", "xvm1"]) put(path.join("builder", "xvb", f + ".py"));
  for (const f of ["__init__", "kernels", "dspfile", "dsm1", "dsh1", "sprites"]) put(path.join("builder", "mshb", f + ".py"));
  put(path.join("builder", "data", "mshvsf", "dsh_params.json"));
  for (const f of fs.readdirSync(path.join(ROOT, "builder", "data", "mshvsf", "hot"))) put(path.join("builder", "data", "mshvsf", "hot", f));
  py.runPython("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, '/msh/builder')\nfrom mshb import kernels, sprites");
  py.pyimport("mshb.kernels").use_js(MSK.forPyodide(), XVK.forPyodide());
  const sprites = py.pyimport("mshb.sprites");
  py.runPython("def _job(t, c, p, v):\n    return sprites.encode_job(t, c, open(p, 'rb').read(), v)");
  const job = py.globals.get("_job");
  console.log("runtime ready in %ss", ((Date.now() - t0) / 1000).toFixed(1));

  const files = path.join(REF, "files");
  py.FS.mkdirTree("/in");
  // sprites.jobs() looks at a directory Pyodide cannot see: the same list, built here
  const TIERS = sprites.TIERS.toJs();
  const hotDir = path.join(ROOT, "builder", "data", "mshvsf", "hot");
  const allJobs = [];
  for (const t of TIERS) for (let c = 0; c < 0x17; c++) {
    const lab = "SP_PL" + c.toString(16).toUpperCase().padStart(2, "0");
    if (!fs.existsSync(path.join(files, lab + ".DSP"))) continue;
    if (t.includes("_hot") && !fs.existsSync(path.join(hotDir, lab + ".json"))) continue;
    allJobs.push([t, c, lab]);
  }
  const chars = pos.length === 0 ? [0x01, 0x0B, 0x10] : pos[0] === "all" ? null : pos.map((x) => parseInt(x, 16));
  const todo = allJobs.filter(([t, c]) => (!chars || chars.includes(c)) && (!tiers || tiers.includes(t)));
  const per = {}; let ok = 0; const bad = [];
  for (const [t, c, lab] of todo) {
    const stock = fs.readFileSync(path.join(files, lab + ".DSP")), ref = fs.readFileSync(path.join(REF, t, lab + ".DSP"));
    const ts = Date.now();
    py.FS.writeFile("/in/" + lab + ".DSP", stock);
    const r = job(t, c, "/in/" + lab + ".DSP", verify);
    const out = r.toJs(); r.destroy();
    const dt = (Date.now() - ts) / 1000;
    const same = out.length === ref.length && Buffer.compare(Buffer.from(out), ref) === 0;
    ok += same; if (!same) bad.push(t + "/" + lab);
    (per[t] = per[t] || []).push(dt);
    console.log("%s %s %s %d %ss", t.padEnd(10), lab, same ? "identical" : "DIFFERENT", out.length, dt.toFixed(2));
  }
  console.log("\nper tier: jobs here, s/job, jobs in a build, estimated s");
  let est = 0;
  for (const t of TIERS) {
    const n = allJobs.filter((j) => j[0] === t).length;
    if (!per[t]) { console.log("  %s  (not run, %d jobs)", t.padEnd(10), n); continue; }
    const avg = per[t].reduce((a, b) => a + b, 0) / per[t].length; est += avg * n;
    console.log("  " + t.padEnd(10) + String(per[t].length).padStart(4) + avg.toFixed(2).padStart(7) + String(n).padStart(4) + (avg * n).toFixed(1).padStart(8));
  }
  console.log("%d of %d identical; estimated all %d jobs: %ss (one worker); rss %d MB, total %ss", ok, todo.length, allJobs.length,
    est.toFixed(0), process.memoryUsage().rss / 1048576 | 0, ((Date.now() - t0) / 1000).toFixed(0));
  if (bad.length) { console.log("DIFFERENT:", bad.join(" ")); process.exit(2); }
  console.log("ALL IDENTICAL");
})().catch((e) => { console.error(e); process.exit(1); });
