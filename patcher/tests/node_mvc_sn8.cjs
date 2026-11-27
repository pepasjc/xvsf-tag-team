/* Developer test: MvC 8 MB arcade voices (games/mvc/tools/snd/sn8build.py) in Pyodide, a few banks under cProfile.
 * PYODIDE_DIR=... node patcher/tests/node_mvc_sn8.cjs DISC.bin mvsc.zip [BANK,...]   (bundle: patcher/xvsf_bundle.zip) */
const fs = require("fs"), path = require("path");
const XVK = require("../src/kernels.js"), MSK = require("../src/kernels_msh.js"), MVK = require("../src/kernels_mvc.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));
(async () => {
  const disc = path.resolve(process.argv[2]), zip = path.resolve(process.argv[3]), banks = (process.argv[4] || "01,02").split(",");
  const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR }); await py.loadPackage(["numpy", "scipy"]);
  py.unpackArchive(new Uint8Array(fs.readFileSync(path.join(__dirname, "..", "xvsf_bundle.zip"))), "zip", { extractDir: "/xvsf" });
  py.FS.mkdir("/in"); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(disc) }, "/in");
  py.FS.mkdir("/arc"); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(zip) }, "/arc");
  py.runPython("import sys; sys.path.insert(0, '/xvsf/builder')");
  const vweb = py.pyimport("mvcb.web"); vweb.use_js_kernels(MVK.forPyodide(), MSK.forPyodide(), XVK.forPyodide());
  const games = py.pyimport("games"); const idn = JSON.parse(games.identify_web("/in/" + path.basename(disc)));
  const t0 = Date.now();
  vweb.prepare("/in/" + path.basename(disc), JSON.stringify(["/arc/" + path.basename(zip)]), idn.sha1, idn.size, () => {}, () => {});
  console.log("prepare", (Date.now() - t0) / 1000, "s");
  py.globals.set("BANKS", banks); py.globals.set("ZIP", "/arc/" + path.basename(zip));
  py.runPython(`
import os, sys, time, cProfile, pstats, io
from mvcb import pipeline
os.environ["VOICEHQ"] = "1"
for q in (pipeline.gdir("/xvsf", "tools", "snd"), "/xvsf/tools"):
    if q not in sys.path: sys.path.insert(0, q)
import sn8build as S8
t = time.time(); arc = S8.arcade_samples([ZIP]); print("samples", round(time.time() - t, 1), "s", flush=True)
pr = cProfile.Profile(); pr.enable()
for n in BANKS:
    t = time.time(); S8.build(n, arc, "arc"); print("bank", n, round(time.time() - t, 1), "s", flush=True)
pr.disable(); s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(25); print(s.getvalue())
`);
})().catch((e) => { console.log(String(e && e.stack || e)); });
