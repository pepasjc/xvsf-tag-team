/* The build worker.  (make.py puts kernels.js and zopfli.js in front of this file and the page starts the
 * result from a Blob, so it also runs when the page is opened from file://.)
 *
 * It loads Pyodide (CPython compiled to WebAssembly), unpacks the bundle (the project's own Python build
 * pipeline: builder/xvb + tools/), mounts the user's files READ-ONLY through WORKERFS - they are read in
 * slices on demand and never copied into memory - and runs the same pipeline as builder/build.py.
 * The hot loops run as JavaScript (kernels.js) instead of numba.
 *
 * 1.2 sound: the ADPCM encoder jobs of the sound banks run in sub-workers (the same script, started from
 * self.location) while this worker encodes the sprites; see builder/xvb/web.py, "encoded in parallel".
 *
 * Messages in:   {type:"init", pyodide, bundle:ArrayBuffer, zopfli:{glue, wasm}}
 *                {type:"disc", file}            verify a disc image
 *                {type:"arcade", files:[...]}   identify an arcade ROM set
 *                {type:"build", flags:[...]}    build with the files given before
 * Messages out:  {type:"ready"} {type:"status", text} {type:"disc", result} {type:"arcade", result}
 *                {type:"progress", stage, frac, text} {type:"log", line} {type:"done", ...} {type:"error", message}
 * Sub-worker:    {type:"snd_encode", i, x:Int32Array, prm:[nblk, s1, s2, K, M, B, R]} -> {type:"snd_done", i, out}
 * Cancelling = the page terminates the worker (and with it its sub-workers) and starts a new one.
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

function soundParallel(meta, inputs, onDone) {
  // -> Promise of the ADPCM blocks of every job, concatenated in plan order; jobs go to the sub-workers longest first
  const n = Math.max(1, Math.min(4, (self.navigator && navigator.hardwareConcurrency || 2) - 1));
  const offs = []; let total = 0;
  for (const m of meta) { offs.push(total); total += 16 * m[3]; }
  const out = new Uint8Array(total), order = meta.map((m, i) => i).sort((a, b) => meta[b][2] - meta[a][2] || a - b);
  return new Promise((resolve, reject) => {
    let next = 0, done = 0;
    const subs = [];
    const give = (w) => {
      if (next >= order.length) return;
      const i = order[next++], m = meta[i], x = inputs.slice(m[1], m[1] + m[2]);
      w.postMessage({ type: "snd_encode", i, x, prm: m.slice(3) }, [x.buffer]);
    };
    for (let k = 0; k < Math.min(n, order.length); k++) {
      const w = new Worker(self.location.href);
      w.onmessage = (ev) => {
        const r = ev.data;
        if (r.type !== "snd_done") { subs.forEach((s) => s.terminate()); reject(new Error("sound sub-worker: " + (r.message || r.type))); return; }
        out.set(r.out, offs[r.i]); done++; onDone(done, order.length);
        if (done === order.length) { subs.forEach((s) => s.terminate()); resolve(out); } else give(w);
      };
      w.onerror = (ev) => { subs.forEach((s) => s.terminate()); reject(new Error("sound sub-worker: " + (ev.message || "error"))); };
      subs.push(w); give(w);
    }
  });
}

function sndEncode(m) {
  const [nblk, s1, s2, K, M, B, R] = m.prm, out = new Uint8Array(16 * nblk);
  XVK.snd_encode(m.x, nblk, s1, s2, K, M, B, R, out);
  self.postMessage({ type: "snd_done", i: m.i, out }, [out.buffer]);
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
  // the sound encoder jobs to the sub-workers, the sprites here meanwhile; then wait for the sound
  web.prepare("/in/disc.bin");
  const plan = web.sound_plan("/in/disc.bin", JSON.stringify(arcade), JSON.stringify(flags));
  const meta = JSON.parse(plan.get(0)), arr = plan.get(1), buf = arr.getBuffer("i32"), inputs = buf.data.slice();
  buf.release(); arr.destroy(); plan.destroy();
  let sndDone = 0, sndTotal = meta.length, spritesDone = false;
  const sound = meta.length ? soundParallel(meta, inputs, (d, t) => { sndDone = d; if (spritesDone) progress("sound", d / t, d + " of " + t); }) : null;
  web.sprites(progress, log);
  spritesDone = true;
  if (sound) {
    progress("sound", sndDone / sndTotal, sndDone + " of " + sndTotal);
    const out = await sound;
    log("sound: " + meta.length + " encoder jobs done in sub-workers");
    web.sound_results(JSON.stringify(meta), out);
    progress("sound", 1, "");
  }
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
    else if (m.type === "snd_encode") sndEncode(m);
  } catch (e) {
    post({ type: "error", message: String((e && e.message) || e), during: m.type });
  }
};
