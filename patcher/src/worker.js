/* The build worker.  (make.py puts kernels.js, kernels_msh.js and zopfli.js in front of this file and the page starts
 * the result from a Blob, so it also runs when the page is opened from file://.)
 *
 * It loads Pyodide (CPython compiled to WebAssembly), unpacks the bundle (the project's own Python build pipelines:
 * builder/xvb for X-Men vs. Street Fighter, builder/mshb for Marvel Super Heroes vs. Street Fighter, and the tools
 * they run), mounts the user's files READ-ONLY through WORKERFS - they are read in slices on demand and never copied
 * into memory - and runs the same pipeline as builder/build.py.  The hot loops run as JavaScript (kernels*.js)
 * instead of numba.  Which game: builder/games.py, from the files on the disc.
 *
 * Long independent jobs run in sub-workers (the same script, started from self.location):
 *   XvSF sound: the ADPCM encoder jobs of the sound banks (JavaScript only, no Python in the sub-worker);
 *   MSHvSF: the sprite tiers (one tier of one character per job), the sound levels (one character's bank per job) and
 *   the 8 MB arcade frames, in sub-workers that load Pyodide themselves.
 * See builder/xvb/web.py and builder/mshb/web.py.
 *
 * Messages in:   {type:"init", pyodide, bundle:ArrayBuffer, zopfli:{glue, wasm}}
 *                {type:"disc", file}            identify + verify a disc image
 *                {type:"arcade", files:[...]}   identify an arcade ROM set (for the game of the disc)
 *                {type:"build", flags:[...], opts:{...}}   build with the files given before
 * Messages out:  {type:"ready"} {type:"status", text} {type:"disc", result} {type:"arcade", result}
 *                {type:"progress", stage, frac, text} {type:"log", line} {type:"done", ...} {type:"error", message}
 * Sub-worker:    {type:"snd_encode", i, x:Int32Array, prm:[nblk, s1, s2, K, M, B, R]} -> {type:"snd_done", i, out}
 *                {type:"spr_init", pyodide, bundle} -> {type:"spr_ready"};  {type:"spr_job", i, tier, char, data} -> {type:"spr_done", i, out}
 *                {type:"arc_job", i, disc:File, arcade:[File]} -> {type:"arc_done", i, ok, message, files:{name: bytes}}
 *                {type:"snd_char", i, char, data:PLxx_10.A0} -> {type:"snd_char_done", i, files:{bank cache file: bytes}}
 * Cancelling = the page terminates the worker (and with it its sub-workers) and starts a new one.
 */
"use strict";
let py = null, web = null, mweb = null, vweb = null, games = null, cfg = null, zopfliReady = false;
let mountSeq = 0, discPath = null;
let disc = null, discInfo = null, arcade = [], arcadeFiles = [], game = null;
let replyPort = null;                         // a sub-worker answers through the port the page gave it
const post = (m, t) => (replyPort || self).postMessage(m, t || []);

/* Sub-workers are started by the PAGE (patcher/src/app.js "spawn"), which hands this worker one end of a
 * MessageChannel and the sub-worker the other: a worker cannot start another one from a blob: URL when the page is
 * opened from file:// (opaque origin).  spawnSub() returns a stand-in with the Worker interface the pools use. */
let subSeq = 0;
const subPending = {}, subErr = {};
function spawnSub() {
  const id = ++subSeq, q = [];
  const sp = { port: null, onmessage: null, onerror: null,
    postMessage(m, t) { if (sp.port) sp.port.postMessage(m, t || []); else q.push([m, t || []]); },
    terminate() { post({ type: "kill", id }); if (sp.port) sp.port.close(); delete subPending[id]; delete subErr[id]; } };
  subPending[id] = (port) => { sp.port = port; port.onmessage = (ev) => sp.onmessage && sp.onmessage(ev); for (const [m, t] of q) port.postMessage(m, t); q.length = 0; };
  subErr[id] = (message) => sp.onerror && sp.onerror({ message });
  post({ type: "spawn", id });
  return sp;
}

// (2026-11-27) an arcade zip keeps its own name after "setN_" (a MERGED zip: the set named like the zip comes first;
// the builders strip the prefix)
const arcName = (f, i) => "set" + i + "_" + String(f.name || "set.zip").replace(/[^A-Za-z0-9._-]/g, "_").replace(/(\.zip)?$/i, ".zip");
function mount(dir, items) {
  // items: [{name, data: File}]; WORKERFS reads them with FileReaderSync, slice by slice
  try { py.FS.unmount(dir); } catch (e) { /* not mounted yet */ }
  try { py.FS.mkdir(dir); } catch (e) { /* exists */ }
  py.FS.mount(py.FS.filesystems.WORKERFS, { blobs: items }, dir);
}

async function loadRuntime(pyodideUrl, bundle, quiet) {
  if (!quiet) post({ type: "status", text: "Loading the Python runtime" });
  importScripts(pyodideUrl + "pyodide.js");
  const p = await loadPyodide({ indexURL: pyodideUrl });
  if (!quiet) post({ type: "status", text: "Loading numpy" });
  await p.loadPackage("numpy", { messageCallback: () => {} });
  if (!quiet) post({ type: "status", text: "Unpacking the builder" });
  p.unpackArchive(bundle, "zip", { extractDir: "/xvsf" });
  p.runPython("import sys; sys.path.insert(0, '/xvsf/builder')");
  return p;
}

async function init(c) {
  cfg = c;
  py = await loadRuntime(cfg.pyodide, cfg.bundle.slice(0), false);
  web = py.pyimport("xvb.web");
  web.use_js_kernels(XVK.forPyodide());
  mweb = py.pyimport("mshb.web");
  mweb.use_js_kernels(MSK.forPyodide(), XVK.forPyodide());
  if (py.FS.analyzePath("/xvsf/builder/mvcb/web.py").exists) {          // MvC (builder/mvcb): before games (it enables the game there)
    vweb = py.pyimport("mvcb.web");
    vweb.use_js_kernels(MVK.forPyodide(), MSK.forPyodide(), XVK.forPyodide());
  }
  games = py.pyimport("games");
  const options = { xvsf: JSON.parse(web.options_available()), mshvsf: JSON.parse(mweb.options_available()) };
  if (vweb) options.mvc = JSON.parse(vweb.options_available());
  post({ type: "ready", options });
}

async function needZopfli() {
  if (zopfliReady) return;
  const deflate = await Promise.race([loadZopfli(cfg.zopfli.glue, cfg.zopfli.wasm),
    new Promise((_, rej) => setTimeout(() => rej(new Error("the zopfli module did not start")), 30000))]);
  web.use_js_zopfli((data, iterations) => { const u = data.toJs(); data.destroy(); return deflate(u, iterations); });
  zopfliReady = true;
}

function verifyDisc(file) {
  disc = file; discInfo = null; game = null;
  discPath = "/in" + (++mountSeq);              // a new mount point per file: no unmount of a file Python may still hold
  mount(discPath, [{ name: "disc.bin", data: file }]);
  discPath += "/disc.bin";
  let last = 0;
  const r = JSON.parse(games.identify_web(discPath, (f) => { const t = Date.now(); if (t - last > 100) { last = t; post({ type: "progress", stage: "hash", frac: f }); } }));
  game = r.game || null;
  if (r.status === "ok") discInfo = r;
  post({ type: "disc", result: r });
}

function verifyArcade(files) {
  arcade = []; arcadeFiles = [];
  if (!files.length) { post({ type: "arcade", result: { status: "none" } }); return; }
  const dir = "/arc" + (++mountSeq);
  mount(dir, files.map((f, i) => ({ name: arcName(f, i), data: f })));
  const paths = files.map((f, i) => dir + "/" + arcName(f, i));
  // the set belongs to the game of the disc; before a disc is recognised, the first game that accepts it
  let r = null;
  for (const g of game ? [game] : (vweb ? ["xvsf", "mshvsf", "mvc"] : ["xvsf", "mshvsf"])) {
    r = JSON.parse((g === "mvc" ? vweb : g === "mshvsf" ? mweb : web).check_arcade(JSON.stringify(paths))); r.game = g;
    if (r.status === "ok") break;
  }
  if (!game && r.status !== "ok") r.message = "This is not an arcade ROM set of X-Men vs. Street Fighter" + (vweb ? ", Marvel Super Heroes vs. Street Fighter or Marvel vs. Capcom. " : " or Marvel Super Heroes vs. Street Fighter. ") + r.message;
  files.forEach((f, i) => { r.message = r.message.split(paths[i]).join(f.name); });       // messages name the user's file, not the mount point
  if (r.status === "ok") { arcade = paths; arcadeFiles = files; }
  post({ type: "arcade", result: r });
}

/* ---------------------------------------------------------------- sub-worker pools */
// (2026-11-27) pool sizes from the machine: a Python sub-worker holds its own Pyodide (400-700 MB), an encoder
// sub-worker a few MB.  navigator.deviceMemory: GB, rounded (some browsers cap it at 8; absent = 8).  The page may force
// sizes (?pyw=N&jsw=N, for tests).  The bytes do not depend on them (only the speed does).
function poolSizes() {
  const cores = (self.navigator && navigator.hardwareConcurrency) || 2;
  const mem = (self.navigator && navigator.deviceMemory) || 8;
  let py = Math.max(1, Math.min(5, Math.floor(mem / 4), cores - 1));      // 8 GB: 2 (measured peak 3.7 GB with 2 + 4)
  let js = Math.max(1, Math.min(mem >= 8 ? 15 : mem >= 4 ? 6 : 2, cores - 1));
  const f = (cfg && cfg.pool) || {};
  if (f.py > 0) py = f.py | 0;
  if (f.js > 0) js = f.js | 0;
  return { py, js, cores, mem };
}

const nSubs = (reserve) => Math.max(1, Math.min(4, (self.navigator && navigator.hardwareConcurrency || 2) - reserve));

function soundParallel(meta, inputs, onDone, n) {
  // -> Promise of the ADPCM blocks of every job, concatenated in plan order; jobs go to the sub-workers longest first
  n = n || nSubs(1);
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
      const w = spawnSub();
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

function pyParallel(jobs, onResult, onDone, n) {
  // MSHvSF jobs for sub-workers with their own Pyodide: {kind: "spr", tier, char, data} (one sprite tier of one
  // character) and {kind: "arcade", disc, arcade} (the 8 MB arcade frames: the user's files are handed over as File
  // objects and mounted there read-only).  Jobs in order (longest first) -> Promise; results to onResult(job, result)
  return new Promise((resolve, reject) => {
    let next = 0, done = 0;
    const subs = [];
    const fail = (msg) => { subs.forEach((s) => s.terminate()); reject(new Error("sub-worker: " + msg)); };
    const give = (w) => {
      if (next >= jobs.length) return;
      const i = next++, j = jobs[i];
      if (j.kind === "spr") { const data = j.data(); w.postMessage({ type: "spr_job", i, tier: j.tier, char: j.char, data }, [data.buffer]); }
      else if (j.kind === "snd") { const data = j.data(); w.postMessage({ type: "snd_char", i, char: j.char, data }, [data.buffer]); }
      else if (j.kind === "msnd") { const data = j.data(); w.postMessage({ type: "msnd", i, name: j.name, env: j.env, data }, [data.buffer]); }
      else w.postMessage({ type: "arc_job", i, disc: j.disc, arcade: j.arcade });
    };
    for (let k = 0; k < Math.min(n, jobs.length); k++) {
      const w = spawnSub();
      w.onmessage = (ev) => {
        const r = ev.data;
        if (r.type === "spr_ready") { give(w); return; }
        if (r.type === "log") { post(r); return; }
        if (r.type !== "spr_done" && r.type !== "arc_done" && r.type !== "snd_char_done") { fail(r.message || r.type); return; }
        try { onResult(jobs[r.i], r); } catch (e) { fail(String(e && e.message || e)); return; }
        done++; onDone(done, jobs.length, jobs[r.i]);
        if (done === jobs.length) { subs.forEach((s) => s.terminate()); resolve(); } else give(w);
      };
      w.onerror = (ev) => fail(ev.message || "error");
      subs.push(w);
      w.postMessage({ type: "spr_init", pyodide: cfg.pyodide, bundle: cfg.bundle.slice(0), game });
    }
  });
}

// (2026-11-27) the ADPCM encoder compiled to WebAssembly (patcher/wasm/adpcm: the same search, byte for byte, about 2x
// the JavaScript loop); JavaScript when WebAssembly is not there or a job does not fit it
let adpcmWasm;
function adpcmEncoder() {
  if (adpcmWasm === undefined) {
    adpcmWasm = null;
    try {
      if (typeof ADPCM_WASM_B64 === "string" && typeof WebAssembly === "object") {
        const bin = Uint8Array.from(atob(ADPCM_WASM_B64), (c) => c.charCodeAt(0));
        adpcmWasm = new WebAssembly.Instance(new WebAssembly.Module(bin), {}).exports;
      }
    } catch (e) { adpcmWasm = null; }
  }
  return adpcmWasm;
}
function sndEncode(m) {
  const [nblk, s1, s2, K, M, B, R] = m.prm, out = new Uint8Array(16 * nblk);
  const E = adpcmEncoder();
  if (E && m.x.length <= E.max_samples()) {
    new Int32Array(E.memory.buffer, E.x_ptr(), m.x.length).set(m.x);
    const rc = E.encode(m.x.length, nblk, s1, s2, K, M, B, R);
    if (rc === -2) throw new Error("snd_encode: error sum beyond 2**53");
    if (rc === 0) out.set(new Uint8Array(E.memory.buffer, E.out_ptr(), 16 * nblk));
    else XVK.snd_encode(m.x, nblk, s1, s2, K, M, B, R, out);
  } else XVK.snd_encode(m.x, nblk, s1, s2, K, M, B, R, out);
  post({ type: "snd_done", i: m.i, out }, [out.buffer]);
}

let sub = null, subPy = null;                 // a Python sub-worker's own Pyodide
async function sprInit(m) {
  subPy = await loadRuntime(m.pyodide, m.bundle, true);
  subPy.pyimport("xvb.web").use_js_kernels(XVK.forPyodide());      // the sound kernels (tools/snd) too
  if (m.game === "mvc") {                                           // MvC: one sound bank per job (builder/mvcb/web.py)
    sub = subPy.pyimport("mvcb.web");
    sub.use_js_kernels(MVK.forPyodide(), MSK.forPyodide(), XVK.forPyodide());
  } else {
    sub = subPy.pyimport("mshb.web");
    sub.use_js_kernels(MSK.forPyodide(), XVK.forPyodide());
  }
  post({ type: "spr_ready" });
}
function sprJob(m) {
  const out = sub.sprite_job(m.tier, m.char, m.data);
  const u8 = out.toJs(); out.destroy && out.destroy();
  post({ type: "spr_done", i: m.i, out: u8 }, [u8.buffer]);
}
function sndJob(m) {
  const names = JSON.parse(sub.sound_char(m.char, m.data)), files = {}, bufs = [];
  for (const name of names) { const b = sub.sound_file(name), u8 = b.toJs(); b.destroy(); files[name] = u8; bufs.push(u8.buffer); }
  post({ type: "snd_char_done", i: m.i, files }, bufs);
}
let fr8Paths = null;
function mvFr8Job(m) {
  py = subPy;
  if (!fr8Paths) {                                   // the user's files, mounted once per sub-worker (read in slices)
    mount("/in", [{ name: "disc.bin", data: m.disc }]);
    mount("/arc", m.arcade.map((f, i) => ({ name: arcName(f, i), data: f })));
    fr8Paths = m.arcade.map((f, i) => "/arc/" + arcName(f, i));
  }
  const r = sub.fr8_job(m.kind, m.x, JSON.stringify(fr8Paths), "/in/disc.bin"), meta = r.get(0), b = r.get(1), data = b.toJs();
  b.destroy(); r.destroy();
  post({ type: "mfr8_done", i: m.i, meta, data }, [data.buffer]);
}
function mvTierJob(m) {
  const b = sub.tier_job(m.entry, m.names, m.srcs), out = b.toJs(); b.destroy && b.destroy();
  post({ type: "mtier_done", i: m.i, out }, [out.buffer]);
}
function mvSndPlan(m) {
  const plan = sub.sound_bank_plan(m.name, m.data, JSON.stringify(m.env));
  const meta = plan.get(0), arr = plan.get(1), buf = arr.getBuffer("i32"), inputs = buf.data.slice();
  buf.release(); arr.destroy(); plan.destroy();
  post({ type: "msnd_plan_done", i: m.i, meta, inputs }, [inputs.buffer]);
}
function mvSndJob(m) {
  const names = JSON.parse(m.meta ? sub.sound_bank(m.name, m.data, JSON.stringify(m.env), m.meta, m.res) : sub.sound_bank(m.name, m.data, JSON.stringify(m.env))), files = {}, bufs = [];
  for (const name of names) { const b = sub.sound_file(name), u8 = b.toJs(); b.destroy(); files[name] = u8; bufs.push(u8.buffer); }
  post({ type: "snd_char_done", i: m.i, files }, bufs);
}
function arcJob(m) {
  py = subPy;
  mount("/in", [{ name: "disc.bin", data: m.disc }]);
  mount("/arc", m.arcade.map((f, i) => ({ name: arcName(f, i), data: f })));
  const paths = m.arcade.map((f, i) => "/arc/" + arcName(f, i));
  const r = JSON.parse(sub.arcade_sub(JSON.stringify(paths), "/in/disc.bin", (line) => post({ type: "log", line: String(line) })));
  const files = {}, bufs = [];
  if (r.ok) for (const name of r.files) { const b = sub.arcade_file(name), u8 = b.toJs(); b.destroy(); files[name] = u8; bufs.push(u8.buffer); }
  post({ type: "arc_done", i: m.i, ok: r.ok, message: r.message || "", code: r.code || "", files }, bufs);
}

/* ---------------------------------------------------------------- the builds */
function planSound(w, ...args) {
  const plan = w.sound_plan(...args);
  const meta = JSON.parse(plan.get(0)), arr = plan.get(1), buf = arr.getBuffer("i32"), inputs = buf.data.slice();
  buf.release(); arr.destroy(); plan.destroy();
  return { meta, inputs };
}

function makeProgress() {
  let lastP = 0, lastKey = "";
  return (stage, frac, text) => {
    const t = Date.now(), key = stage + "|" + text;
    if (key !== lastKey || frac >= 1 || t - lastP > 150) { lastKey = key; lastP = t; post({ type: "progress", stage, frac, text: text || "" }); }
  };
}
const log = (line) => post({ type: "log", line: String(line) });

async function buildXvsf(flags) {
  // the sound encoder jobs to the sub-workers, the sprites here meanwhile; then wait for the sound
  if (arcade.length) await needZopfli();
  const progress = makeProgress();
  web.prepare(discPath);
  const { meta, inputs } = planSound(web, discPath, JSON.stringify(arcade), JSON.stringify(flags));
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
  return { w: web, info: JSON.parse(web.build(discPath, JSON.stringify(arcade), JSON.stringify(flags), "", discInfo.sha1, discInfo.size, progress, log)) };
}

async function buildMsh(flags, ram8) {
  // every long job in sub-workers that run Python themselves, longest first: the 8 MB arcade frames, the sound levels
  // (one character's bank per job), the sprite tiers (one tier of one character per job)
  const progress = makeProgress();
  // 1.1 8 MB with an arcade set: the arcade voices (tools/snd/sn8build.py: its peak limiter uses scipy.ndimage)
  if (arcade.length) { post({ type: "status", text: "Loading scipy" }); await py.loadPackage("scipy", { messageCallback: () => {} }); }
  progress("extract", 0, "");
  mweb.prepare(discPath);
  progress("extract", 1, "");
  const bytesOf = (f) => { const b = f(), u = b.toJs(); b.destroy(); return u; };
  const jobs = [];
  if (arcade.length) jobs.push({ kind: "arcade", disc, arcade: arcadeFiles });
  for (let c = 0; c <= 0x17; c++) jobs.push({ kind: "snd", char: c, data: () => bytesOf(() => mweb.a0_of(c)) });     // 0x17: COMMON.SE
  const stock = {};
  const dataOf = (ch) => () => { if (!stock[ch]) stock[ch] = bytesOf(() => mweb.stock_dsp(ch)); return stock[ch].slice(); };
  for (const [tier, ch] of JSON.parse(mweb.sprite_jobs())) jobs.push({ kind: "spr", tier, char: ch, data: dataOf(ch) });
  // sub-workers: each holds its own Pyodide (about 400 MB); up to 5
  const nPy = poolSizes().py;
  const count = { spr: 0, snd: 0, arcade: 0 }, total = { spr: 0, snd: 0, arcade: 0 };
  jobs.forEach((j) => total[j.kind]++);
  const report = (d) => progress("prep", d / jobs.length, "graphics " + count.spr + " of " + total.spr + ", sound " + count.snd + " of " + total.snd +
    (total.arcade ? ", arcade frames " + (count.arcade ? "done" : "running") : ""));
  const tS = Date.now();
  let arcFail = null;
  report(0);
  await pyParallel(jobs, (j, r) => {
    if (j.kind === "spr") mweb.sprite_put(j.tier, j.char, r.out);
    else if (j.kind === "snd") for (const [name, u8] of Object.entries(r.files)) mweb.sound_put(name, u8);
    else if (!r.ok) arcFail = r;
    else { for (const [name, u8] of Object.entries(r.files)) mweb.arcade_put(name, u8); log("arcade frames: " + Object.keys(r.files).length + " files after " + ((Date.now() - tS) / 1000).toFixed(1) + " s"); }
    count[j.kind]++;
  }, (d) => report(d), nPy);
  log("graphics + sound: " + jobs.length + " jobs in " + nPy + " sub-workers in " + ((Date.now() - tS) / 1000).toFixed(1) + " s");
  if (arcFail) return { w: mweb, info: { ok: false, code: arcFail.code, message: arcFail.message } };
  mweb.sprites_done();
  progress("prep", 1, "");
  return { w: mweb, info: JSON.parse(mweb.build(discPath, JSON.stringify(arcade), JSON.stringify(flags), "", discInfo.sha1, discInfo.size, progress, log, !!ram8)) };
}

async function buildMvc() {
  // MvC (builder/mvcb): this worker verifies + extracts; (2026-11-27) then, all at once: the sound banks (three phases,
  // mvcSound) and the sprite tiers of the derive step on a pool of Python sub-workers, the ADPCM encoder jobs on
  // JavaScript sub-workers, the rest of the derive step here; then the build here (it finds every file made).
  // With the arcade set: arcade frames (in process) + arcade voices (tools/snd/sn8build.py: scipy)
  const progress = makeProgress();
  if (arcade.length) { post({ type: "status", text: "Loading scipy" }); await py.loadPackage("scipy", { messageCallback: () => {} }); }
  const banks = JSON.parse(vweb.prepare(discPath, JSON.stringify(arcade), discInfo.sha1, discInfo.size, progress, log));
  const ps = poolSizes(), nPy = ps.py, cores = ps.cores;
  log("sub-workers: " + nPy + " Python, " + ps.js + " encoder (" + ps.cores + " cores, deviceMemory " + ps.mem + ")");
  const pool = pyPool(nPy, "mvc");
  try {
    let err = null;
    // (2026-11-27) 8 MB: the arcade frames, one character / assist per job, first in the queue (the longest jobs)
    const fjobs = JSON.parse(vweb.frames_plan(discPath, JSON.stringify(arcade)));
    let fdone = 0;
    const tF = Date.now();
    const frames = Promise.all(fjobs.map(([kind, x]) => pool.submit({ type: "mfr8", kind, x, disc, arcade: arcadeFiles }).then((r) => {
      const [name, ent, desc, chtab] = JSON.parse(r.meta);
      vweb.frames_put(kind, x, name, r.data, JSON.stringify(ent), JSON.stringify(desc), chtab);
      fdone++; progress("prep", fdone / fjobs.length, "arcade frames " + fdone + " of " + fjobs.length);
    }))).then(() => { if (fjobs.length) { vweb.frames_done(); log("arcade frames: " + fjobs.length + " jobs in sub-workers, done after " + ((Date.now() - tF) / 1000).toFixed(1) + " s"); } })
      .catch((e) => { err = err || e; });
    progress("sound", 0, "");
    const snd = mvcSound(pool, banks, progress, cores).catch((e) => { err = err || e; });
    const tD = Date.now(); let tiers = 0, back = 0;
    const pend = [];
    for (;;) {
      if (err) throw err;
      const r = JSON.parse(vweb.derive_step(0.2, true));
      for (const i of r.jobs) {
        const j = vweb.derive_job(i), ej = j.get(0), nj = j.get(1), bl = j.get(2);
        const srcs = []; for (let k = 0; k < bl.length; k++) { const x = bl.get(k), u = x.toJs(); x.destroy(); srcs.push(u); }
        bl.destroy(); j.destroy(); tiers++;
        pend.push(pool.submit({ type: "mtier", entry: ej, names: nj, srcs }, srcs.map((u) => u.buffer))
          .then((res) => { vweb.derive_result(i, res.out); back++; }).catch((e) => { err = err || e; }));
      }
      progress("derive", r.frac, "");
      if (r.frac >= 1) break;
      await new Promise((res) => setTimeout(res, r.wait ? 20 : 0));
    }
    log("derive done after " + ((Date.now() - tD) / 1000).toFixed(1) + " s (" + tiers + " tiers in sub-workers; sound meanwhile)");
    await Promise.all(pend);
    await snd;
    await frames;
    if (err) throw err;
  } finally { pool.close(); }
  return { w: vweb, info: JSON.parse(vweb.build(discPath, JSON.stringify(arcade), "", discInfo.sha1, discInfo.size, progress, log)) };
}

function pyPool(n, game_) {
  // n sub-workers with their own Pyodide; submit(message, transfer) -> Promise of the reply, first come first served
  // (jobs of several kinds share the pool); close() ends them
  const subs = [], queue = [], idle = [];
  let seq = 0; const waiting = {};
  const pump = () => {
    while (idle.length && queue.length) {
      const w = idle.shift(), [m, t] = queue.shift();
      w.busy = m.i; w.postMessage(m, t || []);
    }
  };
  for (let k = 0; k < n; k++) {
    const w = spawnSub(); subs.push(w);
    w.onmessage = (ev) => {
      const r = ev.data;
      if (r.type === "spr_ready") { idle.push(w); pump(); return; }
      if (r.type === "log") { post(r); return; }
      const cb = waiting[w.busy]; delete waiting[w.busy]; w.busy = null; idle.push(w);
      if (cb) { if (r.type === "error" || typeof r.i !== "number") cb.rej(new Error("sub-worker: " + (r.message || r.type))); else cb.res(r); }
      pump();
    };
    w.onerror = (ev) => { const cb = waiting[w.busy]; if (cb) cb.rej(new Error("sub-worker: " + (ev.message || "error"))); };
    w.postMessage({ type: "spr_init", pyodide: cfg.pyodide, bundle: cfg.bundle.slice(0), game: game_ });
  }
  const submit = (m, t) => new Promise((res, rej) => { m.i = ++seq; waiting[m.i] = { res, rej }; queue.push([m, t]); pump(); });
  return { submit, close: () => subs.forEach((s) => s.terminate()) };
}

function jsPool(n) {
  // n JavaScript-only sub-workers (ADPCM encoder): submit(x Int32Array, prm) -> Promise of the blocks; close()
  const subs = [], queue = [], idle = [], waiting = {};
  let seq = 0;
  const pump = () => {
    while (idle.length && queue.length) {
      const w = idle.shift(), j = queue.shift();
      w.busy = j.i; w.postMessage({ type: "snd_encode", i: j.i, x: j.x, prm: j.prm }, [j.x.buffer]);
    }
  };
  for (let k = 0; k < n; k++) {
    const w = spawnSub(); subs.push(w); idle.push(w);
    w.onmessage = (ev) => {
      const r = ev.data, cb = waiting[w.busy]; delete waiting[w.busy]; w.busy = null; idle.push(w);
      if (cb) { if (r.type !== "snd_done") cb.rej(new Error("sound sub-worker: " + (r.message || r.type))); else cb.res(r.out); }
      pump();
    };
    w.onerror = (ev) => { const cb = waiting[w.busy]; if (cb) cb.rej(new Error("sound sub-worker: " + (ev.message || "error"))); };
  }
  const submit = (x, prm) => new Promise((res, rej) => { const i = ++seq; waiting[i] = { res, rej }; queue.push({ i, x, prm }); pump(); });
  return { submit, close: () => subs.forEach((s) => s.terminate()) };
}

async function mvcSound(pool, banks, progress, cores) {
  // (2026-11-26/27) MvC sound, every bank in three steps, the banks overlapping: (1) the bank once in a Python
  // sub-worker with the ADPCM encoder only noting its jobs; (2) its encoder jobs on the JavaScript-only pool (one
  // sub-worker per core; most of the sound work), longest first; (3) the bank again in a Python sub-worker, the encoder
  // taking the results.  Same kernel, same bytes as one pass.
  const bytesOf = (f) => { const b = f(), u = b.toJs(); b.destroy(); return u; };
  const nJs = poolSizes().js, enc = jsPool(nJs);
  const tS = Date.now(); let nJobs = 0, jobsDone = 0, banksDone = 0, tPlan = 0, nDup = 0;
  const seen = new Map();
  const report = () => progress("sound", (banksDone + (nJobs ? jobsDone / nJobs : 0)) / (banks.length + 1),
                                "bank " + banksDone + " of " + banks.length + (nJobs ? ", encoder job " + jobsDone + " of " + nJobs : ""));
  try {
    await Promise.all(banks.map(async ([name, env]) => {
      let data = bytesOf(() => vweb.sound_src(name));
      const r = await pool.submit({ type: "msnd_plan", name, env, data }, [data.buffer]);
      tPlan = Math.max(tPlan, Date.now() - tS);
      const meta = JSON.parse(r.meta), inputs = r.inputs; nJobs += meta.length; report();
      const offs = [0]; for (const m of meta) offs.push(offs[offs.length - 1] + 16 * m[3]);
      const res = new Uint8Array(offs[offs.length - 1]);
      const order = meta.map((m, i) => i).sort((a, b) => meta[b][2] - meta[a][2] || a - b);
      await Promise.all(order.map((i) => {
        const m = meta[i];                              // (the same job in another bank: encoded once; key = SHA-1 of input + settings)
        if (!seen.has(m[0])) seen.set(m[0], enc.submit(inputs.slice(m[1], m[1] + m[2]), m.slice(3)));
        else nDup++;
        return seen.get(m[0]).then((out) => { res.set(out, offs[i]); jobsDone++; report(); });
      }));
      data = bytesOf(() => vweb.sound_src(name));
      const f = await pool.submit({ type: "msnd", name, env, data, meta: r.meta, res }, [data.buffer, res.buffer]);
      for (const [n, u8] of Object.entries(f.files)) vweb.sound_put(n, u8);
      banksDone++; report();
    }));
  } finally { enc.close(); }
  log("sound: " + banks.length + " banks, " + nJs + " encoder sub-workers, " + nJobs + " encoder jobs (" + nDup + " the same as another bank's): last plan after " + (tPlan / 1000).toFixed(1) +
      " s, all done after " + ((Date.now() - tS) / 1000).toFixed(1) + " s");
}

async function build(flags, ram8) {
  if (!discInfo) throw new Error("no verified disc image");
  const t0 = Date.now();
  const { w, info } = game === "mvc" ? await buildMvc() : game === "mshvsf" ? await buildMsh(flags, ram8) : await buildXvsf(flags);
  if (!info.ok) { post({ type: "failed", code: info.code, message: info.message }); return; }
  const progress = makeProgress();
  // checksum of the result, streamed
  post({ type: "progress", stage: "digest", frac: 0, text: "" });
  const dg = JSON.parse(w.result_digest((f) => progress("digest", f, "")));
  // the image: slices of the user's file + the sectors this build made.  A Blob of Blobs: nothing is copied.
  const parts = []; let newBytes = 0;
  const n = w.result_run_count();
  for (let i = 0; i < n; i++) {
    const r = w.result_run(i), kind = r.get(0), first = r.get(1), x = r.get(2);
    if (kind === "src") parts.push(disc.slice(first, first + x));
    else { const u8 = x.toJs(); parts.push(u8); newBytes += u8.length; x.destroy && x.destroy(); }
    r.destroy();
  }
  const blob = new Blob(parts, { type: "application/octet-stream" });
  if (blob.size !== dg.size) throw new Error("internal error: assembled image has the wrong size");
  post({ type: "done", blob, name: info.name, cue: info.cue, sha1: dg.sha1, crc32: dg.crc32, size: dg.size, newBytes, game,
         expected: w.expected(info.variant, info.arcade_set || "", JSON.stringify(info.flags)),
         heapMB: Math.round(py._module.HEAPU8.length / 1048576),      // size the WebAssembly memory grew to
         variant: info.variant, arcadeSet: info.arcade_set || "", times: info.times, seconds: (Date.now() - t0) / 1000, blobs: info.blobs });
}

async function handle(m) {
  try {
    if (m.type === "init") await init(m);
    else if (m.type === "disc") verifyDisc(m.file);
    else if (m.type === "arcade") verifyArcade(m.files);
    else if (m.type === "build") await build(m.flags, m.ram8);
    else if (m.type === "snd_encode") sndEncode(m);
    else if (m.type === "spr_init") await sprInit(m);
    else if (m.type === "spr_job") sprJob(m);
    else if (m.type === "arc_job") arcJob(m);
    else if (m.type === "snd_char") sndJob(m);
    else if (m.type === "msnd") mvSndJob(m);
    else if (m.type === "msnd_plan") mvSndPlan(m);
    else if (m.type === "mtier") mvTierJob(m);
    else if (m.type === "mfr8") mvFr8Job(m);
  } catch (e) {
    post({ type: "error", message: String((e && e.message) || e), during: m.type });
  }
}

self.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === "port") { replyPort = m.port; replyPort.onmessage = (e) => handle(e.data); return; }      // a sub-worker
  if (m.type === "spawned") { const f = subPending[m.id]; if (f) f(m.port); else m.port.close(); return; }
  if (m.type === "suberror") { const f = subErr[m.id]; if (f) f(m.message); return; }
  handle(m);
};
