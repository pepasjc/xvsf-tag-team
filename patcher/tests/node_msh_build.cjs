/* Developer harness: the browser's MSHvSF build under Node (same Pyodide, same bundle, same JavaScript kernels), with
 * the sub-worker jobs run one after the other in this process.  Prints stage times and the SHA-1 of the result.
 *
 *   python patcher/make.py --bundle-only
 *   PYODIDE_DIR=.../node_modules/pyodide node patcher/tests/node_msh_build.cjs DISC.bin [ARCADE.zip ...] [--flag ...]
 *     (no --flag: the release flags, as the page builds them by default)
 *   env RAM8=1: the 8 MB loader without an arcade set;  SPRITES_FROM=DIR: take the sprite tiers from DIR/<tier>/ instead of encoding them (to test the rest quickly)
 */
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const XVK = require("../src/kernels.js");
const MSK = require("../src/kernels_msh.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));

(async () => {
  const args = process.argv.slice(2);
  let flags = args.filter((a) => a.startsWith("--")); const files = args.filter((a) => !a.startsWith("--")).map((f) => path.resolve(f));
  const t0 = Date.now(), T = {};
  const lap = (k, t) => { T[k] = ((Date.now() - t) / 1000); console.log("  %s %ss", k, T[k].toFixed(1)); };
  const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR });
  await py.loadPackage("numpy");
  py.unpackArchive(new Uint8Array(fs.readFileSync(path.join(__dirname, "..", "xvsf_bundle.zip"))), "zip", { extractDir: "/xvsf" });
  const mounts = {};
  files.forEach((f, i) => { const m = "/in" + i; py.FS.mkdir(m); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(f) }, m); mounts[f] = m + "/" + path.basename(f); });
  py.runPython("import sys; sys.path.insert(0, '/xvsf/builder')");
  const web = py.pyimport("xvb.web"); web.use_js_kernels(XVK.forPyodide());
  const mweb = py.pyimport("mshb.web"); mweb.use_js_kernels(MSK.forPyodide(), XVK.forPyodide());
  const games = py.pyimport("games");
  console.log("runtime ready in %ss", ((Date.now() - t0) / 1000).toFixed(1));
  const disc = mounts[files[0]], arcade = files.slice(1).map((f) => mounts[f]);
  let t = Date.now();
  const idn = JSON.parse(games.identify_web(disc)); lap("identify", t);
  console.log("identify:", idn.status, idn.game, idn.message);
  if (idn.status !== "ok") process.exit(1);
  if (!flags.length) flags = JSON.parse(mweb.tool_flags(true, "off"));
  if (arcade.length) { const r = JSON.parse(mweb.check_arcade(JSON.stringify(arcade))); console.log("arcade:", r.status, r.message); }
  const log = (line) => { if (process.env.VERBOSE) console.log("   " + line); };
  t = Date.now(); mweb.prepare(disc); lap("prepare", t);
  t = Date.now();
  // the page's path: one job per character (here in this process, one after the other)
  for (let c = 0; c <= 0x17; c++) {          // 0x17: COMMON.SE
    const tc = Date.now(), a0 = mweb.a0_of(c), u = a0.toJs(); a0.destroy();
    const names = JSON.parse(mweb.sound_char(c, u));
    for (const n of names) { const b = mweb.sound_file(n), d = b.toJs(); b.destroy(); mweb.sound_put(n, d); }
    if (process.env.VERBOSE) console.log("   sound %d: %d files %ss", c, names.length, ((Date.now() - tc) / 1000).toFixed(1));
  }
  lap("sound, 24 bank jobs (one thread)", t);
  t = Date.now();
  const jobs = JSON.parse(mweb.sprite_jobs());
  if (process.env.SPRITES_FROM) {
    for (const [tier, ch] of jobs) mweb.sprite_put(tier, ch, new Uint8Array(fs.readFileSync(path.join(process.env.SPRITES_FROM, tier, "SP_PL" + ch.toString(16).toUpperCase().padStart(2, "0") + ".DSP"))));
  } else {
    let k = 0;
    for (const [tier, ch] of jobs) {
      const tj = Date.now(), b = mweb.stock_dsp(ch), d = b.toJs(); b.destroy();
      const r = mweb.sprite_job(tier, ch, d), u8 = r.toJs(); r.destroy && r.destroy();
      mweb.sprite_put(tier, ch, u8);
      if (process.env.VERBOSE || ++k % 20 === 0) console.log("   sprite %d/%d %s %s %ss", k, jobs.length, tier, ch, ((Date.now() - tj) / 1000).toFixed(1));
    }
  }
  mweb.sprites_done(); lap("sprite jobs (one thread)", t);
  if (arcade.length) {
    t = Date.now();
    const r = JSON.parse(mweb.arcade_sub(JSON.stringify(arcade), disc, log));
    if (!r.ok) { console.log("arcade failed:", r.message); process.exit(1); }
    for (const n of r.files) { const b = mweb.arcade_file(n), u8 = b.toJs(); b.destroy(); mweb.arcade_put(n, u8); }
    lap("arcade frames", t);
  }
  t = Date.now();
  const info = JSON.parse(mweb.build(disc, JSON.stringify(arcade), JSON.stringify(flags), "", idn.sha1, idn.size, () => {}, log, !!process.env.RAM8));
  lap("build", t);
  if (!info.ok) { console.log("build failed:", info.code, info.message); process.exit(1); }
  console.log("times:", JSON.stringify(info.times));
  t = Date.now();
  const dg = JSON.parse(mweb.result_digest()); lap("digest", t);
  const exp = mweb.expected(info.variant, info.arcade_set || "", JSON.stringify(info.flags));
  console.log("%s  %s  %s", info.name, dg.sha1, exp ? (exp === dg.sha1 ? "= expected" : "*** expected " + exp) : "(no reference)");
  console.log("total %ss, WebAssembly memory %d MB", ((Date.now() - t0) / 1000).toFixed(1), Math.round(py._module.HEAPU8.length / 1048576));
  if (process.env.OUT) {      // write the image (slices of the input + new sectors), to compare with the CLI build
    const fd = fs.openSync(process.env.OUT, "w"), src = fs.openSync(files[0], "r");
    const n = mweb.result_run_count();
    for (let i = 0; i < n; i++) {
      const r = mweb.result_run(i), kind = r.get(0), first = r.get(1), x = r.get(2);
      if (kind === "src") { const b = Buffer.alloc(1 << 22); for (let o = 0; o < x; o += b.length) { const k = Math.min(b.length, x - o); fs.readSync(src, b, 0, k, first + o); fs.writeSync(fd, b, 0, k); } }
      else { const u8 = x.toJs(); fs.writeSync(fd, u8); x.destroy && x.destroy(); }
      r.destroy();
    }
    fs.closeSync(fd);
  }
  process.exit(exp && exp !== dg.sha1 ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
