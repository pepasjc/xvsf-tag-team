/* Tag Hack Patcher - the page logic (main thread).
 *
 * The page itself does very little: it hands the files the user picked to a Web Worker (worker.js), which
 * runs the real build in Pyodide, and shows what comes back.  File objects are passed by reference; the
 * 400 MB image is never read into memory here.  The finished image arrives as a Blob that is made of
 * slices of the user's own file plus the rewritten sectors, so "downloading" it copies from disk to disk.
 */
"use strict";
const CFG = JSON.parse(document.getElementById("cfg").textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
/* the little Markdown README.md uses: **bold**, `code`, [text](url) */
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*(.+?)\*/g, "<em>$1</em>");
const mb = (n) => (n / 1048576).toFixed(1) + " MB";
const secs = (s) => (s < 60 ? s.toFixed(0) + " s" : Math.floor(s / 60) + " min " + String(Math.round(s % 60)).padStart(2, "0") + " s");
const b64bytes = (s) => { const bin = atob(s.trim()), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; };

/* ------------------------------------------------------------------ state */
const state = {
  ready: false, options: {},
  game: null,                            // "xvsf" | "mshvsf": from the disc (builder/games.py)
  discFile: null, disc: null,            // File, verification result
  arcadeFiles: [], arcade: null,         // Files, identification result
  building: false, result: null, t0: 0, stageT0: {}, urls: [],
};
let worker = null, workerUrl = null;
const subs = {};                          // the build's sub-workers, started here for the worker (worker.js spawnSub)

/* ------------------------------------------------------------------ theme */
(() => {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) { /* private window */ }
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  $("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
  };
})();

/* ------------------------------------------------------------------ the side panel (README.md, patcher/src/mshvsf.md) */
const GAME_NAMES = { xvsf: "X-Men vs. Street Fighter", mshvsf: "Marvel Super Heroes vs. Street Fighter", mvc: "Marvel vs. Capcom" };
function drawAbout() {
  const g = state.game;
  let h = "";
  if (LANG === "pt") {                     // patcher/src/about_pt.md: the same sections in Portuguese
    const R = CFG.about_pt[g || "intro"] || {};
    for (const [title, items] of Object.entries(R)) h += "<h3>" + esc(title) + "</h3><ul>" + items.map((x) => "<li>" + md(x) + "</li>").join("") + "</ul>";
  } else if (g === "xvsf") {
    const R = CFG.readme, does = R["What the hack does"] || [];
    const isControl = (t) => /HP \+ HK|Default buttons/.test(t);
    h = "<h3>What this does</h3><ul>" + does.filter((t) => !isControl(t)).map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
    h += "<h3>Controls</h3><ul>" + does.filter(isControl).map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
    const RF = "Restored animation frames (optional, 8 MB)";
    if (R[RF]) h += "<h3>Restored frames (optional, 8 MB)</h3><ul>" + R[RF].filter((t, i) => i > 0).map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
    if (R["Known issues"]) h += "<h3>Known issues</h3><ul>" + R["Known issues"].map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
    if (R["How it fits in 2 MB"]) h += "<h3>How it fits in 2 MB</h3>" + R["How it fits in 2 MB"].map((t) => "<p>" + md(t) + "</p>").join("");
  } else {
    const R = g === "mshvsf" ? CFG.about.mshvsf : CFG.about.intro;
    for (const [title, items] of Object.entries(R)) h += "<h3>" + esc(title) + "</h3><ul>" + items.map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
  }
  $("about").innerHTML = h;
}
function drawStatic() {
  applyStatic();
  $("legal").innerHTML = (LANG === "pt" ? Object.values(CFG.about_pt.legal || {})[0] || [] : CFG.readme["Legal"] || []).map(md).join(" ");
  $("fine").innerHTML = t("fine", esc(/^https?:/.test(CFG.pyodide) ? t("pyo.pinned", new URL(CFG.pyodide).host) : t("pyo.site")));
  drawAbout();
}
drawStatic();
$("lang").onclick = () => {
  LANG = LANG === "pt" ? "en" : "pt";
  try { localStorage.setItem("lang", LANG); } catch (e) { /* private window */ }
  drawStatic(); setArcadeHint(); redraw();
};

/* ------------------------------------------------------------------ status boxes */
function status(id, kind, html) {
  const el = $(id);
  if (!kind) { el.hidden = true; return; }
  el.hidden = false; el.className = "status " + kind; el.innerHTML = html;
}

/* ------------------------------------------------------------------ the worker */
function startWorker() {
  state.ready = false;
  $("runtime").textContent = t("rt.preparing");
  const src = new TextDecoder().decode(b64bytes($("worker-src").textContent));
  if (!workerUrl) workerUrl = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
  worker = new Worker(workerUrl);
  worker.onmessage = (ev) => onWorker(ev.data);
  worker.onerror = (ev) => fatal(t("fatal.worker", ev.message || "unknown error"));
  const bundle = b64bytes($("bundle").textContent).buffer;
  const qp = new URLSearchParams(location.search), pool = { py: +qp.get("pyw") || 0, js: +qp.get("jsw") || 0 };   // (tests: forced pool sizes)
  worker.postMessage({ type: "init", pyodide: new URL(CFG.pyodide, location.href).href, bundle, zopfli: JSON.parse($("zopfli").textContent), pool }, [bundle]);
}

function fatal(msg) {
  state.ready = false; state.building = false;
  $("runtime").textContent = "";
  status("st-build", "bad", esc(msg) + "<br><small>" + t("fatal.more") + "</small>");
  refresh();
}

function onWorker(m) {
  if (m.type === "spawn") {
    // a sub-worker for the worker: started here (a worker cannot start one from a blob: URL under file://), connected
    // to the worker by a MessageChannel
    const w = new Worker(workerUrl), ch = new MessageChannel(), me = worker;
    w.onerror = (ev) => { if (worker === me) worker.postMessage({ type: "suberror", id: m.id, message: ev.message || "error" }); };
    w.postMessage({ type: "port", port: ch.port2 }, [ch.port2]);
    worker.postMessage({ type: "spawned", id: m.id, port: ch.port1 }, [ch.port1]);
    subs[m.id] = w;
    return;
  }
  if (m.type === "kill") { if (subs[m.id]) subs[m.id].terminate(); delete subs[m.id]; return; }
  if (m.type === "status") $("runtime").textContent = t("rt." + m.text) + " …";
  else if (m.type === "ready") {
    state.ready = true; state.options = m.options; $("runtime").textContent = "";
    if (state.discFile && !state.disc) worker.postMessage({ type: "disc", file: state.discFile });      // files picked while loading
    if (state.arcadeFiles.length && !state.arcade) worker.postMessage({ type: "arcade", files: state.arcadeFiles });
    refresh();
  } else if (m.type === "disc") { state.disc = m.result; setGame(m.result.game || null); showDisc(); refresh(); }
  else if (m.type === "arcade") { state.arcade = m.result; showArcade(); refresh(); }
  else if (m.type === "progress") onProgress(m);
  else if (m.type === "log") onLog(m.line);
  else if (m.type === "done") onDone(m);
  else if (m.type === "failed") { endBuild(); status("st-build", "bad", t("err.failed", esc(m.message))); }
  else if (m.type === "error") {
    if (m.during === "init") fatal(t("fatal.init", m.message));
    else { endBuild(); status("st-build", "bad", t("err.internal", esc(m.message))); onLog("ERROR " + m.message); }
  }
}

/* ------------------------------------------------------------------ choosing files */
function wireDrop(zone, input, take) {
  const z = $(zone), inp = $(input);
  inp.onchange = () => { if (inp.files.length) take([...inp.files]); inp.value = ""; };
  z.ondragover = (e) => { e.preventDefault(); z.classList.add("over"); };
  z.ondragleave = () => z.classList.remove("over");
  z.ondrop = (e) => { e.preventDefault(); z.classList.remove("over"); if (e.dataTransfer.files.length) take([...e.dataTransfer.files]); };
  z.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inp.click(); } };
}
// a file dropped next to the zones must not navigate away from the page
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", (e) => e.preventDefault());

function takeDisc(files) {
  if (state.building) return;
  // the image is the big file; a .cue only names it
  const img = files.filter((f) => !/\.cue$/i.test(f.name)).sort((a, b) => b.size - a.size)[0];
  clearResult();
  if (!img) {
    state.discFile = null; state.disc = null;
    status("st-disc", "bad", t("disc.cueonly"));
    return refresh();
  }
  state.discFile = img; state.disc = null; setGame(null);
  $("drop-disc").classList.add("has");
  $("drop-disc").querySelector(".drop-title").removeAttribute("data-i18n");      // (a language switch keeps the file name)
  $("drop-disc").querySelector(".drop-title").textContent = img.name;
  status("st-disc", "busy", t("disc.checkingsize", esc(img.name), mb(img.size)));
  if (state.ready) worker.postMessage({ type: "disc", file: img });
  refresh();
}

function setGame(g) {
  if (g === state.game) return;
  state.game = g;
  document.body.dataset.game = g || "";
  setArcadeHint();
  if (state.arcadeFiles.length && state.ready && g && !(state.arcade && state.arcade.game === g)) { state.arcade = null; status("st-arcade", "busy", t("arc.checking")); worker.postMessage({ type: "arcade", files: state.arcadeFiles }); }
  drawAbout();
}

function setArcadeHint() {
  $("arcade-hint").innerHTML = t(state.game === "mvc" ? "arc.hint.mvc" : state.game === "mshvsf" ? "arc.hint.mshvsf" : state.game === "xvsf" ? "arc.hint.xvsf" : "arc.hint");
}
setArcadeHint();

/* a message of the builder (English) in the page's language: what it is, then the builder's own text */
function builderMsg(r) {
  const pt = (I18N[LANG]["disc.status"] || {})[r.status];
  return pt ? pt + "<br><small>" + esc(r.message) + "</small>" : esc(r.message);
}

function showDisc() {
  const r = state.disc;
  if (!r) return;
  if (r.status === "ok") status("st-disc", "ok", t("disc.ok", esc(r.message)) + '<br><span class="mono">SHA-1 ' + r.sha1 + "</span>");
  else if (r.status === "unsupported") status("st-disc", "warn", builderMsg(r));
  else status("st-disc", "bad", builderMsg(r) + (r.sha1 ? '<br><span class="mono">' + t("disc.thissha") + " " + r.sha1 + "</span>" : ""));
}

function takeArcade(files) {
  if (state.building) return;
  clearResult();
  state.arcadeFiles = files.slice(0, 3); state.arcade = null;
  $("drop-arcade").classList.add("has");
  $("drop-arcade").querySelector(".drop-title").removeAttribute("data-i18n");
  $("drop-arcade").querySelector(".drop-title").innerHTML = files.map((f) => esc(f.name)).join(" + ") + ' <button type="button" class="ghost" id="arc-clear" data-i18n="arc.remove" data-i18n-title="arc.remove.title" title="' + t("arc.remove.title") + '">' + t("arc.remove") + "</button>";
  $("arc-clear").onclick = (e) => { e.preventDefault(); e.stopPropagation(); clearArcade(); };
  status("st-arcade", "busy", t("arc.checking"));
  if (state.ready) worker.postMessage({ type: "arcade", files: state.arcadeFiles });
  refresh();
}

function clearArcade() {
  state.arcadeFiles = []; state.arcade = null; clearResult();
  $("drop-arcade").classList.remove("has");
  $("drop-arcade").querySelector(".drop-title").setAttribute("data-i18n", "arc.drop");
  $("drop-arcade").querySelector(".drop-title").innerHTML = t("arc.drop");
  status("st-arcade", null);
  if (state.ready) worker.postMessage({ type: "arcade", files: [] });
  refresh();
}

function showArcade() {
  const r = state.arcade;
  if (!r || r.status === "none") return status("st-arcade", null);
  const name = r.known === false && LANG === "pt" ? t("arc.unknownname") : esc(r.message);
  if (r.status === "ok") status("st-arcade", r.known === false ? "warn" : "ok", r.known === false ? t("arc.unknown", name) : t("arc.ok", name));
  else status("st-arcade", "bad", esc(r.message).replace(/\n/g, "<br>") + "<br><small>" + t("arc.bad.more") + "</small>");
}

/* ------------------------------------------------------------------ what will be built */
function flags() {
  // always the release image (builder/xvb/pipeline.py and builder/mshb/pipeline.py tool_flags() defaults): the page has no options
  // (patcher/make.py puts each builder's tool_flags() defaults into CFG.release_flags: 2 MB / with an arcade set)
  const r = (CFG.release_flags || {})[state.game] || {};
  return (withArcade() ? r["8mb"] : r["2mb"]).slice();
}
const ram8 = () => false;                 // (MSHvSF: the 8 MB loader comes with an arcade set)
const withArcade = () => state.arcadeFiles.length > 0 && state.arcade && state.arcade.status === "ok" && state.arcade.game === state.game;

function expectedFor(variant, setName, fl) {
  const key = JSON.stringify(fl.slice().sort());
  const e = ((CFG.known[state.game] || {}).expected || []).find((x) => x.variant === variant && (x.arcade_set || "") === (setName || "") &&
    (x.flags ? JSON.stringify(x.flags) === key : !fl.length));             // (MvC: one configuration per variant, no flags)
  return e ? e.sha1 : "";
}

const LI = (x, off) => "<li" + (off ? ' class="off"' : "") + "><div>" + x + "</div></li>";

function refresh() {
  const with8 = withArcade(), fl = state.game ? flags() : [];
  const exp = state.game ? expectedFor(with8 || ram8() ? "8mb" : "2mb", with8 ? state.arcade.message : "", fl) : "";
  let h = "";
  if (!state.game) h = LI(t("plan.none"), true);
  else {
    const k = state.game === "mvc" ? "plan.mvc." : state.game === "mshvsf" ? "plan.msh." : "plan.xv.";
    h = LI(t(k + "tag")) + LI(t(k + "snd", with8)) + LI(t("plan.ach")) + LI(t(k + "extras"));
    h += with8 ? LI(t(k + "rf", esc(state.arcade.message))) : LI(t("plan.rf.off"), true);
    h += LI(t("plan.out") + " <code>.bin</code> + <code>.cue</code>" + '<br><span class="mono">' + (exp ? t("plan.exp") + " " + exp : t("plan.noexp")) + "</span>", !exp);
  }
  $("plan").innerHTML = h;
  const discOk = state.disc && state.disc.status === "ok";
  const arcOk = !state.arcadeFiles.length || (state.arcade && state.arcade.status === "ok");
  $("go").disabled = !(state.ready && discOk && arcOk && state.game) || state.building;
  $("go").textContent = t(with8 ? "build.go8" : "build.go");
  if (!state.building && !state.result) {
    if (discOk && arcOk && state.ready) status("st-build", "busy", t(state.game === "mvc" ? "ready.mvc" : state.game === "mshvsf" ? "ready.msh" : with8 ? "ready.8" : "ready.2"));
    else if (!$("st-build").classList.contains("bad")) status("st-build", null);
  }
}

/* ------------------------------------------------------------------ building */
const STAGES_MSH = [["extract", 2], ["prep", 85], ["disc", 6], ["digest", 4]];              // titles: t("st." + key)
const STAGES = [["extract", 2], ["sprites", 75], ["sound", 10], ["arcade", 230], ["disc", 3], ["digest", 4]];
const STAGES_MVC = [["extract", 2], ["derive", 40], ["sound", 40], ["disc", 15], ["digest", 3]];      // builder/mvcb/pipeline.py run()
let run = null;                           // {stages: [{key, title, weight, frac, state, t0, t}], sub: counters}

function startBuild() {
  const with8 = withArcade();
  clearResult(); $("log").textContent = "";
  state.building = true; state.t0 = performance.now();
  run = { stages: (state.game === "mvc" ? STAGES_MVC : state.game === "mshvsf" ? STAGES_MSH : STAGES).filter((s) => s[0] !== "arcade" || with8).map(([key, weight]) => ({ key, weight: key === "disc" && with8 ? 100 : weight, frac: 0, state: "", t0: 0, t: 0 })), packed: 0, chars: 0 };
  $("progress").hidden = false; $("cancel").hidden = false; status("st-build", null);
  drawProgress(); refresh();
  worker.postMessage({ type: "build", flags: flags(), ram8: ram8() });
  run.timer = setInterval(drawProgress, 500);
}

function onProgress(m) {
  if (m.stage === "hash") { if (!state.disc) status("st-disc", "busy", t("disc.checking", esc(state.discFile.name)) + " " + Math.round(m.frac * 100) + " %"); return; }
  if (!run) return;
  const i = run.stages.findIndex((s) => s.key === m.stage);
  if (i < 0) return;
  run.stages.forEach((s, k) => { if (k < i && s.state !== "done") { s.state = "done"; s.frac = 1; if (s.t0) s.t = (performance.now() - s.t0) / 1000; } });
  const s = run.stages[i];
  if (!s.t0) s.t0 = performance.now();
  s.frac = Math.max(s.frac, m.frac); s.text = m.text || s.text;
  s.state = m.frac >= 1 ? "done" : "run";
  if (s.state === "done") s.t = (performance.now() - s.t0) / 1000;
  drawProgress();
}

function onLog(line) {
  const pre = $("log");
  pre.textContent += line + "\n";
  if (!run) return;
  // finer progress for the two long 8 MB stages, read off the tools' own output
  const st = (k) => run.stages.find((s) => s.key === k);
  if (/^\s*\d+ \S+\s+sprites \d+ -> \d+/.test(line) && st("arcade")) { run.chars++; st("arcade").frac = Math.min(0.97, run.chars / 14); st("arcade").text = line.trim().split(/\s+/)[1]; }
  if (/packed block/.test(line) && st("disc")) { run.packed++; st("disc").frac = Math.min(0.97, 0.05 + run.packed / 20); }
}

function drawProgress() {
  if (!run) return;
  const total = run.stages.reduce((a, s) => a + s.weight, 0), done = run.stages.reduce((a, s) => a + s.weight * s.frac, 0);
  $("bar-fill").style.width = (100 * done / total).toFixed(1) + "%";
  $("stages").innerHTML = run.stages.map((s) => {
    const tm = s.state === "done" ? secs(s.t) : s.state === "run" ? secs((performance.now() - s.t0) / 1000) : "";
    return '<li class="' + s.state + '"><span class="dot"></span><span>' + esc(t("st." + s.key)) + (s.state === "run" && s.text ? " — " + esc(s.text) : "") + '</span><span class="t">' + tm + "</span></li>";
  }).join("") + '<li class="run"><span></span><span class="t">' + t("elapsed") + " " + secs((performance.now() - state.t0) / 1000) + "</span><span></span></li>";
}

function endBuild() {
  state.building = false;
  if (run && run.timer) clearInterval(run.timer);
  $("cancel").hidden = true;
  refresh();
}

function cancelBuild() {
  // the worker is in the middle of a long synchronous computation: stopping it means ending it
  worker.terminate();
  for (const id of Object.keys(subs)) { subs[id].terminate(); delete subs[id]; }
  endBuild(); run = null; $("progress").hidden = true;
  status("st-build", "warn", t("cancelled"));
  state.disc = null; state.arcade = null;
  startWorker();                          // a fresh worker; the files are verified again when it is ready
  if (state.discFile) status("st-disc", "busy", t("disc.checking", esc(state.discFile.name)));
}

function onDone(m) {
  if (run) { run.stages.forEach((s) => { if (s.state !== "done") { s.state = "done"; s.frac = 1; if (s.t0) s.t = (performance.now() - s.t0) / 1000; } }); drawProgress(); }
  endBuild();
  state.result = m;
  const binUrl = URL.createObjectURL(m.blob), cueUrl = URL.createObjectURL(new Blob([m.cue], { type: "text/plain" }));
  state.urls.push(binUrl, cueUrl);
  $("dl-bin").href = binUrl; $("dl-bin").download = m.name + ".bin";
  $("dl-cue").href = cueUrl; $("dl-cue").download = m.name + ".cue";
  m.secs = (performance.now() - state.t0) / 1000;
  drawFacts();
  $("note-8mb").hidden = m.variant !== "8mb";
  $("card-result").hidden = false;
  status("st-build", "ok", t("done"));
  $("card-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function drawFacts() {
  const m = state.result; if (!m) return;
  const verdict = !m.expected ? t("v.none")
    : m.expected === m.sha1 ? '<span class="match">' + t("v.ok") + "</span>" : '<span class="nomatch">' + t("v.bad", m.expected) + "</span>";
  $("facts").innerHTML =
    "<dt>" + t("f.file") + "</dt><dd><code>" + esc(m.name) + ".bin</code> + <code>" + esc(m.name) + ".cue</code> (" + mb(m.size) + ")</dd>" +
    "<dt>" + t("f.contents") + "</dt><dd>" + esc(GAME_NAMES[m.game] || "") + ": " + (m.variant === "8mb" ? t("f.c8", esc(m.arcadeSet)) : t("f.c2")) + "</dd>" +
    '<dt>SHA-1</dt><dd><span class="mono">' + m.sha1 + "</span><br>" + verdict + "</dd>" +
    "<dt>" + t("f.built") + "</dt><dd>" + secs(m.secs) + " · " + t("f.newdata", mb(m.newBytes)) + "</dd>";
}

/* the language changed: every text drawn from the state again (the build itself is not touched) */
function redraw() {
  if (state.disc) showDisc();
  showArcade(); refresh(); drawFacts(); drawProgress();
  if (state.result) status("st-build", "ok", t("done"));
}

function clearResult() {
  state.result = null; $("card-result").hidden = true;
  state.urls.forEach((u) => URL.revokeObjectURL(u)); state.urls = [];
  if (!state.building) { $("progress").hidden = true; run = null; }
}

/* ------------------------------------------------------------------ one .zip with both files (stored, not compressed) */
const CRC_TABLE = (() => { const t = new Uint32Array(256); for (let i = 0; i < 256; i++) { let c = i; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[i] = c >>> 0; } return t; })();
const crc32 = (u8) => { let c = 0xFFFFFFFF; for (let i = 0; i < u8.length; i++) c = CRC_TABLE[(c ^ u8[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };

function zipBlob(entries) {
  // entries: [{name, data: Blob | Uint8Array, size, crc}] -> a ZIP archive as a Blob of the same parts (no copy of the image)
  const enc = new TextEncoder(), parts = [], central = [];
  let offset = 0;
  const DOS_TIME = 0, DOS_DATE = ((2026 - 1980) << 9) | (1 << 5) | 1;       // fixed date: the archive is reproducible
  for (const e of entries) {
    const name = enc.encode(e.name);
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(8, 0, true); lh.setUint16(10, DOS_TIME, true); lh.setUint16(12, DOS_DATE, true);
    lh.setUint32(14, e.crc, true); lh.setUint32(18, e.size, true); lh.setUint32(22, e.size, true); lh.setUint16(26, name.length, true);
    parts.push(lh.buffer, name, e.data);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(12, DOS_TIME, true); ch.setUint16(14, DOS_DATE, true);
    ch.setUint32(16, e.crc, true); ch.setUint32(20, e.size, true); ch.setUint32(24, e.size, true); ch.setUint16(28, name.length, true); ch.setUint32(42, offset, true);
    central.push(ch.buffer, name);
    offset += 30 + name.length + e.size;
  }
  const csize = central.reduce((a, p) => a + p.byteLength, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, entries.length, true); end.setUint16(10, entries.length, true); end.setUint32(12, csize, true); end.setUint32(16, offset, true);
  return new Blob([...parts, ...central, end.buffer], { type: "application/zip" });
}

$("dl-zip").onclick = () => {
  const m = state.result; if (!m) return;
  const cue = new TextEncoder().encode(m.cue);
  const url = URL.createObjectURL(zipBlob([{ name: m.name + ".cue", data: cue, size: cue.length, crc: crc32(cue) }, { name: m.name + ".bin", data: m.blob, size: m.size, crc: m.crc32 }]));
  state.urls.push(url);
  const a = document.createElement("a"); a.href = url; a.download = m.name + ".zip"; document.body.appendChild(a); a.click(); a.remove();
};

/* ------------------------------------------------------------------ go */
wireDrop("drop-disc", "in-disc", takeDisc);
wireDrop("drop-arcade", "in-arcade", takeArcade);
$("go").onclick = startBuild;
$("cancel").onclick = cancelBuild;
refresh();
startWorker();
