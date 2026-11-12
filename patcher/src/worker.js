/* The build worker.  (make.py puts kernels.js and zopfli.js in front of this file and the page starts the
 * result from a Blob, so it also runs when the page is opened from file://.)
 *
 * It loads Pyodide (CPython compiled to WebAssembly), unpacks the bundle (the project's own Python build
 * pipeline: builder/xvb + tools/), mounts the user's files READ-ONLY through WORKERFS - they are read in
 * slices on demand and never copied into memory - and runs the same pipeline as builder/build.py.
 * The hot loops run as JavaScript (kernels.js) instead of numba.
 *
 * Messages in:   {type:"init", pyodide, bundle:ArrayBuffer, zopfli:{glue, wasm}}
 *                {type:"disc", file}            verify a disc image
 *                {type:"arcade", files:[...]}   identify an arcade ROM set
 *                {type:"build", flags:[...]}    build with the files given before
 * Messages out:  {type:"ready"} {type:"status", text} {type:"disc", result} {type:"arcade", result}
 *                {type:"progress", stage, frac, text} {type:"log", line} {type:"done", ...} {type:"error", message}
 * Cancelling = the page terminates the worker and starts a new one.
 */
"use strict";
let py = null, web = null, cfg = null, zopfliReady = false;
let disc = null, discInfo = null, arcade = [];
const post = (m) => self.postMessage(m);

function mount(dir, items) {
  // items: [{name, data: File}]; WORKERFS reads them with FileReaderSync, slice by slice
  try { py.FS.unmount(dir); } catch (e) { /* not mounted yet */ }
  try { py.FS.mkdir(dir); } catch (e) { /* exists */ }
  py.FS.mount(py.FS.filesystems.WORKERFS, { blobs: items }, dir);
}

async function init(c) {
  cfg = c;
  post({ type: "status", text: "Loading the Python runtime" });
  importScripts(cfg.pyodide + "pyodide.js");
  py = await loadPyodide({ indexURL: cfg.pyodide });
  post({ type: "status", text: "Loading numpy" });
  await py.loadPackage("numpy", { messageCallback: () => {} });
  post({ type: "status", text: "Unpacking the builder" });
  py.unpackArchive(cfg.bundle, "zip", { extractDir: "/xvsf" });
  py.runPython("import sys; sys.path.insert(0, '/xvsf/builder')");
  web = py.pyimport("xvb.web");
  web.use_js_kernels(XVK.forPyodide());
  post({ type: "ready", options: JSON.parse(web.options_available()) });
}

async function needZopfli() {
  if (zopfliReady) return;
  const deflate = await Promise.race([loadZopfli(cfg.zopfli.glue, cfg.zopfli.wasm),
    new Promise((_, rej) => setTimeout(() => rej(new Error("the zopfli module did not start")), 30000))]);
  web.use_js_zopfli((data, iterations) => { const u = data.toJs(); data.destroy(); return deflate(u, iterations); });
  zopfliReady = true;
}

function verifyDisc(file) {
  disc = file; discInfo = null;
  mount("/in", [{ name: "disc.bin", data: file }]);
  let last = 0;
  const r = JSON.parse(web.identify("/in/disc.bin", (f) => { const t = Date.now(); if (t - last > 100) { last = t; post({ type: "progress", stage: "hash", frac: f }); } }));
  if (r.status === "ok") discInfo = r;
  post({ type: "disc", result: r });
}

function verifyArcade(files) {
  arcade = [];
  if (!files.length) { post({ type: "arcade", result: { status: "none" } }); return; }
  mount("/arc", files.map((f, i) => ({ name: "set" + i + ".zip", data: f })));
  const paths = files.map((f, i) => "/arc/set" + i + ".zip");
  const r = JSON.parse(web.check_arcade(JSON.stringify(paths)));
  files.forEach((f, i) => { r.message = r.message.split(paths[i]).join(f.name); });       // messages name the user's file, not the mount point
  if (r.status === "ok") arcade = paths;
  post({ type: "arcade", result: r });
}

async function build(flags) {
  if (!discInfo) throw new Error("no verified disc image");
  if (arcade.length) await needZopfli();
  const t0 = Date.now();
  let lastP = 0, lastKey = "";
  const progress = (stage, frac, text) => {
    const t = Date.now(), key = stage + "|" + text;
    if (key !== lastKey || frac >= 1 || t - lastP > 150) { lastKey = key; lastP = t; post({ type: "progress", stage, frac, text: text || "" }); }
  };
  const log = (line) => post({ type: "log", line: String(line) });
  const info = JSON.parse(web.build("/in/disc.bin", JSON.stringify(arcade), JSON.stringify(flags), "", discInfo.sha1, discInfo.size, progress, log));
  if (!info.ok) { post({ type: "failed", code: info.code, message: info.message }); return; }
  // checksum of the result, streamed
  post({ type: "progress", stage: "digest", frac: 0, text: "" });
  const dg = JSON.parse(web.result_digest((f) => progress("digest", f, "")));
  // the image: slices of the user's file + the sectors this build made.  A Blob of Blobs: nothing is copied.
  const parts = []; let newBytes = 0;
  const n = web.result_run_count();
  for (let i = 0; i < n; i++) {
    const r = web.result_run(i), kind = r.get(0), first = r.get(1), x = r.get(2);
    if (kind === "src") parts.push(disc.slice(first, first + x));
    else { const u8 = x.toJs(); parts.push(u8); newBytes += u8.length; x.destroy && x.destroy(); }
    r.destroy();
  }
  const blob = new Blob(parts, { type: "application/octet-stream" });
  if (blob.size !== dg.size) throw new Error("internal error: assembled image has the wrong size");
  post({ type: "done", blob, name: info.name, cue: info.cue, sha1: dg.sha1, crc32: dg.crc32, size: dg.size, newBytes,
         expected: web.expected(info.variant, info.arcade_set || "", JSON.stringify(info.flags)),
         heapMB: Math.round(py._module.HEAPU8.length / 1048576),      // size the WebAssembly memory grew to
         variant: info.variant, arcadeSet: info.arcade_set || "", times: info.times, seconds: (Date.now() - t0) / 1000, blobs: info.blobs });
}

self.onmessage = async (ev) => {
  const m = ev.data;
  try {
    if (m.type === "init") await init(m);
    else if (m.type === "disc") verifyDisc(m.file);
    else if (m.type === "arcade") verifyArcade(m.files);
    else if (m.type === "build") await build(m.flags);
  } catch (e) {
    post({ type: "error", message: String((e && e.message) || e), during: m.type });
  }
};
