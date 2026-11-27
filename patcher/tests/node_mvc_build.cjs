/* Developer harness: the browser's MvC build under Node (same Pyodide, the MvC bundle, the JavaScript kernels).
 *
 *   python patcher/make.py --bundle-only        (-> patcher/xvsf_bundle.zip, MvC included)
 *   PYODIDE_DIR=.../node_modules/pyodide node patcher/tests/node_mvc_build.cjs DISC.bin [mvsc.zip]
 * Prints stage times, the SHA-1 of the result and the expected one (builder/data/mvc/known.json).
 */
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const XVK = require("../src/kernels.js");
const MSK = require("../src/kernels_msh.js");
const MVK = require("../src/kernels_mvc.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));

(async () => {
  const files = process.argv.slice(2).map((f) => path.resolve(f));
  const t0 = Date.now();
  const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR });
  await py.loadPackage("numpy");
  const GATE = require("./gate_hooks.cjs");          // release gate: XVSF_BUNDLE (the page's own bundle), PROBE_MISSING
  py.unpackArchive(new Uint8Array(fs.readFileSync(GATE.bundlePath(__dirname))), "zip", { extractDir: "/xvsf" });
  GATE.install(py);
  const mounts = {};
  files.forEach((f, i) => { const m = "/in" + i; py.FS.mkdir(m); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(f) }, m); mounts[f] = m + "/" + path.basename(f); });
  py.runPython("import sys; sys.path.insert(0, '/xvsf/builder')");
  if (process.env.PRESND) {                         // (debug) the sound cache of a command-line run: skips the sound stage
    py.FS.mkdirTree("/xvsf/games/mvc/build/snd");
    for (const f of fs.readdirSync(process.env.PRESND)) py.FS.writeFile("/xvsf/games/mvc/build/snd/" + f, fs.readFileSync(path.join(process.env.PRESND, f)));
  }
  if (process.env.KEYDBG) {                         // (debug) toolbake key misses -> host folder
    fs.mkdirSync(process.env.KEYDBG, { recursive: true }); py.FS.mkdir("/dbg"); py.FS.mount(py.FS.filesystems.NODEFS, { root: process.env.KEYDBG }, "/dbg");
    py.runPython("import os; os.environ['MVCB_KEYDBG'] = '/dbg'");
  }
  if (process.env.PROFILE) {                        // (developer) cProfile -> host file PROFILE
    fs.mkdirSync(path.dirname(path.resolve(process.env.PROFILE)), { recursive: true }); py.FS.mkdir("/prof");
    py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(path.resolve(process.env.PROFILE)) }, "/prof");
    py.runPython("import os; os.environ['MVCB_PROFILE'] = '/prof/" + path.basename(process.env.PROFILE) + "'");
  }
  if (process.env.CHECKPATCH) py.runPython("import os; os.environ['MVCB_CHECKPATCH'] = '1'");
  const t_log = Date.now();
  const vweb = py.pyimport("mvcb.web"); vweb.use_js_kernels(MVK.forPyodide(), MSK.forPyodide(), XVK.forPyodide());
  const games = py.pyimport("games");
  console.log("runtime ready in %ss", ((Date.now() - t0) / 1000).toFixed(1));
  const disc = mounts[files[0]], arcade = files.slice(1).map((f) => mounts[f]);
  const idn = JSON.parse(games.identify_web(disc));
  console.log("identify:", idn.status, idn.game, idn.message);
  if (idn.status !== "ok") process.exit(1);
  if (arcade.length) { await py.loadPackage("scipy"); console.log("arcade:", vweb.check_arcade(JSON.stringify(arcade))); }
  let last = "", ts = Date.now();
  const progress = (s, f, t) => { if (s !== last) { if (last) console.log("  %s %ss", last, ((Date.now() - ts) / 1000).toFixed(1)); last = s; ts = Date.now(); } };
  const log = (line) => { if (process.env.VERBOSE) console.log("   [%ss] %s", ((Date.now() - t0) / 1000).toFixed(1), line); };
  if (process.env.STACKDUMP) py.runPython(`
import sys, time, traceback
from mvcb import pipeline as _pl
def _sd_hook(tool, m):
    if tool != "mkap8": return
    st = [time.time()]
    def prof(frame, event, arg):
        t = time.time()
        if t - st[0] > ${+process.env.STACKDUMP || 60}:
            st[0] = t
            print("STACK", "".join(traceback.format_stack(frame, limit=12)).replace("\\n", " | ")[-1500:], flush=True)
    sys.setprofile(prof)
_pl.TOOL_HOOKS.append(_sd_hook)
`);
  const t = Date.now();
  const info = JSON.parse(vweb.build(disc, JSON.stringify(arcade), "", idn.sha1, idn.size, progress, log));
  if (last) console.log("  %s %ss", last, ((Date.now() - ts) / 1000).toFixed(1));
  if (!info.ok) { console.log("BUILD FAILED:", info.code, info.message); process.exit(1); }
  console.log("build %ss, %d sectors, %d changed", ((Date.now() - t) / 1000).toFixed(1), info.sectors, info.changed);
  const dg = JSON.parse(vweb.result_digest(() => {}));
  const sha = dg.sha1, exp = vweb.expected(arcade.length ? "8mb" : "2mb", info.arcade_set || "");
  console.log("SHA-1 %s\nexpected %s %s", sha, exp, sha === exp ? "IDENTICAL" : "*** DIFFERENT ***");
  console.log("peak rss %d MB, total %ss", Math.round(process.memoryUsage().rss / 1048576), ((Date.now() - t0) / 1000).toFixed(1));
})();
