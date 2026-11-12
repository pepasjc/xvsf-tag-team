/* Developer harness: run the browser build under Node (same Pyodide, same bundle, same JavaScript kernels).
 * Quicker to iterate on than a browser, and it prints stage times.  Not a substitute for the browser test.
 *
 *   python patcher/make.py --bundle-only
 *   npm i pyodide@0.25.1            (anywhere; pass that folder's node_modules/pyodide as PYODIDE_DIR)
 *   PYODIDE_DIR=.../node_modules/pyodide node patcher/tests/node_build.cjs DISC.bin [ARCADE.zip ...] [--flag ...]
 */
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const XVK = require("../src/kernels.js");
const { loadPyodide } = require(path.join(process.env.PYODIDE_DIR, "pyodide.js"));

(async () => {
  const args = process.argv.slice(2);
  const flags = args.filter((a) => a.startsWith("--")), files = args.filter((a) => !a.startsWith("--")).map((f) => path.resolve(f));
  const t0 = Date.now();
  const py = await loadPyodide({ indexURL: process.env.PYODIDE_DIR });
  await py.loadPackage("numpy");
  py.unpackArchive(new Uint8Array(fs.readFileSync(path.join(__dirname, "..", "xvsf_bundle.zip"))), "zip", { extractDir: "/xvsf" });
  const mounts = {};
  files.forEach((f, i) => {
    const m = "/in" + i; py.FS.mkdir(m); py.FS.mount(py.FS.filesystems.NODEFS, { root: path.dirname(f) }, m);
    mounts[f] = m + "/" + path.basename(f);
  });
  py.runPython("import sys; sys.path.insert(0, '/xvsf/builder')\nfrom xvb import web");
  const web = py.pyimport("xvb.web");
  web.use_js_kernels(XVK.forPyodide());
  const vz = path.join(__dirname, "..", "vendor", "zopfli");
  const deflate = await require("../src/zopfli.js")(fs.readFileSync(path.join(vz, "libzopfli.js"), "utf8"), JSON.parse(fs.readFileSync(path.join(vz, "libzopfli-wasm.json"), "utf8")));
  web.use_js_zopfli((data, iterations) => { const u = data.toJs(); data.destroy(); return deflate(u, iterations); });
  console.log("runtime ready in %ss", ((Date.now() - t0) / 1000).toFixed(1));
  const idn = JSON.parse(web.identify(mounts[files[0]]));
  console.log("identify:", idn.status, idn.message);
  let last = "";
  const progress = (stage, f, text) => { if (stage !== last) { last = stage; console.log("* " + stage); } };
  const log = (line) => { if (process.env.VERBOSE) console.log("   " + line); };
  const t1 = Date.now();
  const info = JSON.parse(web.build(mounts[files[0]], JSON.stringify(files.slice(1).map((f) => mounts[f])), JSON.stringify(flags), "", idn.sha1, idn.size, progress, log));
  console.log(info.ok ? "build ok" : "build FAILED: " + info.message, "in", ((Date.now() - t1) / 1000).toFixed(1), "s");
  if (!info.ok) process.exit(2);
  console.log("times:", JSON.stringify(info.times), "sprites:", JSON.stringify(info.sprites));
  const dg = JSON.parse(web.result_digest());
  console.log("sha1", dg.sha1, "size", dg.size, "expected", web.expected(info.variant, info.arcade_set || "", JSON.stringify(info.flags)));
  // the image as the page assembles it: source slices + new sectors (hash again, from the parts)
  const h = crypto.createHash("sha1"); const fd = fs.openSync(files[0], "r"); let newBytes = 0;
  for (let i = 0; i < web.result_run_count(); i++) {
    const r = web.result_run(i); const kind = r.get(0), first = r.get(1), x = r.get(2);
    if (kind === "src") {
      const buf = Buffer.alloc(1 << 22);
      for (let off = 0; off < x;) { const n = fs.readSync(fd, buf, 0, Math.min(buf.length, x - off), first + off); h.update(buf.subarray(0, n)); off += n; }
    } else { const u8 = x.toJs(); h.update(u8); newBytes += u8.length; }
    r.destroy();
  }
  console.log("sha1 from parts", h.digest("hex"), "new bytes", newBytes, "total", ((Date.now() - t0) / 1000).toFixed(1), "s", "rss MB", (process.memoryUsage().rss / 1048576).toFixed(0));
})().catch((e) => { console.error(e); process.exit(1); });
