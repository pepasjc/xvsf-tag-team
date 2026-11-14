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
  ready: false, options: { title: false, logo: false, title_text: "" },
  discFile: null, disc: null,            // File, verification result
  arcadeFiles: [], arcade: null,         // Files, identification result
  building: false, result: null, t0: 0, stageT0: {}, urls: [],
};
let worker = null;

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

/* ------------------------------------------------------------------ the side panel, from README.md */
(() => {
  const R = CFG.readme, does = R["What it does"] || [];
  const isControl = (t) => /HP \+ HK|Default buttons/.test(t);
  let h = "<h3>What this does</h3><ul>" + does.filter((t) => !isControl(t)).map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
  h += "<h3>Controls</h3><ul>" + does.filter(isControl).map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
  const RF = "Restored frames (8 MB)";
  if (R[RF]) h += "<h3>Restored frames (optional, 8 MB)</h3><ul>" + R[RF].filter((t, i) => i > 0).map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
  if (R["Known issues"]) h += "<h3>Known issues</h3><ul>" + R["Known issues"].map((t) => "<li>" + md(t) + "</li>").join("") + "</ul>";
  if (R["How it works"]) h += "<h3>How it works</h3><p>" + md(R["How it works"][0]) + "</p>";      // the first paragraph: the others link into the repository
  $("about").innerHTML = h;
  $("pyosrc").textContent = /^https?:/.test(CFG.pyodide) ? new URL(CFG.pyodide).host + " (pinned version)" : "this site";
})();

/* ------------------------------------------------------------------ status boxes */
function status(id, kind, html) {
  const el = $(id);
  if (!kind) { el.hidden = true; return; }
  el.hidden = false; el.className = "status " + kind; el.innerHTML = html;
}

/* ------------------------------------------------------------------ the worker */
function startWorker() {
  state.ready = false;
  $("runtime").textContent = "Preparing the builder …";
  const src = new TextDecoder().decode(b64bytes($("worker-src").textContent));
  worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
  worker.onmessage = (ev) => onWorker(ev.data);
  worker.onerror = (ev) => fatal("The build worker stopped: " + (ev.message || "unknown error"));
  const bundle = b64bytes($("bundle").textContent).buffer;
  worker.postMessage({ type: "init", pyodide: new URL(CFG.pyodide, location.href).href, bundle, zopfli: JSON.parse($("zopfli").textContent) }, [bundle]);
}

function fatal(msg) {
  state.ready = false; state.building = false;
  $("runtime").textContent = "";
  status("st-build", "bad", esc(msg) + '<br><small>Reload the page to try again. The builder needs to download its Python runtime once (about 25 MB); after that it works from the browser cache.</small>');
  refresh();
}

function onWorker(m) {
  if (m.type === "status") $("runtime").textContent = m.text + " …";
  else if (m.type === "ready") {
    state.ready = true; state.options = m.options; $("runtime").textContent = "";
    if (state.discFile && !state.disc) worker.postMessage({ type: "disc", file: state.discFile });      // files picked while loading
    if (state.arcadeFiles.length && !state.arcade) worker.postMessage({ type: "arcade", files: state.arcadeFiles });
    refresh();
  } else if (m.type === "disc") { state.disc = m.result; showDisc(); refresh(); }
  else if (m.type === "arcade") { state.arcade = m.result; showArcade(); refresh(); }
  else if (m.type === "progress") onProgress(m);
  else if (m.type === "log") onLog(m.line);
  else if (m.type === "done") onDone(m);
  else if (m.type === "failed") { endBuild(); status("st-build", "bad", esc(m.message)); }
  else if (m.type === "error") {
    if (m.during === "init") fatal("Could not start the builder: " + m.message);
    else { endBuild(); status("st-build", "bad", "The build stopped with an internal error: " + esc(m.message) + "<br><small>The log below has the details.</small>"); onLog("ERROR " + m.message); }
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
    status("st-disc", "bad", "A <code>.cue</code> file only names the disc image. Add the <code>.bin</code> file it belongs to.");
    return refresh();
  }
  state.discFile = img; state.disc = null;
  $("drop-disc").classList.add("has");
  $("drop-disc").querySelector(".drop-title").textContent = img.name;
  status("st-disc", "busy", "Checking " + esc(img.name) + " (" + mb(img.size) + ") …");
  if (state.ready) worker.postMessage({ type: "disc", file: img });
  refresh();
}

function showDisc() {
  const r = state.disc;
  if (r.status === "ok") status("st-disc", "ok", "✓ " + esc(r.message) + ' — verified original<br><span class="mono">SHA-1 ' + r.sha1 + "</span>");
  else status("st-disc", "bad", esc(r.message) + (r.sha1 ? '<br><span class="mono">SHA-1 of this file: ' + r.sha1 + "</span>" : ""));
}

function takeArcade(files) {
  if (state.building) return;
  clearResult();
  state.arcadeFiles = files.slice(0, 3); state.arcade = null;
  $("drop-arcade").classList.add("has");
  $("drop-arcade").querySelector(".drop-title").innerHTML = files.map((f) => esc(f.name)).join(" + ") + ' <button type="button" class="ghost" id="arc-clear" title="Remove the arcade set">remove</button>';
  $("arc-clear").onclick = (e) => { e.preventDefault(); e.stopPropagation(); clearArcade(); };
  status("st-arcade", "busy", "Checking the ROM set …");
  if (state.ready) worker.postMessage({ type: "arcade", files: state.arcadeFiles });
  refresh();
}

function clearArcade() {
  state.arcadeFiles = []; state.arcade = null; clearResult();
  $("drop-arcade").classList.remove("has");
  $("drop-arcade").querySelector(".drop-title").innerHTML = "Drop the arcade <code>.zip</code> here, or click to choose";
  status("st-arcade", null);
  if (state.ready) worker.postMessage({ type: "arcade", files: [] });
  refresh();
}

function showArcade() {
  const r = state.arcade;
  if (!r || r.status === "none") return status("st-arcade", null);
  if (r.status === "ok") status("st-arcade", "ok", "✓ " + esc(r.message) + " — recognised");
  else status("st-arcade", "bad", esc(r.message).replace(/\n/g, "<br>") + "<br><small>Remove the set to build the normal tag hack, or pick another file.</small>");
}

/* ------------------------------------------------------------------ what will be built */
function flags() {
  // the same rules as pipeline.tool_flags(): release configuration unless switched off
  const f = [], with8 = withArcade();
  if ($("opt-logo").checked && state.options.logo) f.push("--logo");
  if (!with8 && $("opt-title").checked && state.options.title) f.push("--title");      // with an arcade set the version line is always on
  if (document.querySelector('input[name="buttons"]:checked').value === "stock") f.push("--nopad");
  return f;
}
const withArcade = () => state.arcadeFiles.length > 0 && state.arcade && state.arcade.status === "ok";

function expectedFor(variant, setName, fl) {
  const key = JSON.stringify(fl.slice().sort());
  const e = (CFG.known.expected || []).find((x) => x.variant === variant && (x.arcade_set || "") === (setName || "") && JSON.stringify(x.flags) === key);
  return e ? e.sha1 : "";
}

function refresh() {
  const with8 = withArcade(), fl = flags();
  const exp = expectedFor(with8 ? "8mb" : "2mb", with8 ? state.arcade.message : "", fl);
  let h = "<li><div><strong>Tag hack for the stock 2 MB console</strong> — four full characters per match, tag with HP + HK, no disc access during a fight.</div></li>";
  h += "<li><div><strong>Full sound for every character in a battle</strong> — partners and tagged-in characters use their own complete sound bank, rebuilt from your disc" +
       (with8 ? " (8 MB: the original sample quality for almost every team, plus Wolverine's third tag voice from your arcade set)." : ".") + "</div></li>";
  const extras = [fl.includes("--logo") ? "boot card" : "", with8 || fl.includes("--title") ? "version line on the main menu" : "", fl.includes("--nopad") ? "stock buttons" : ""].filter(Boolean);
  h += "<li" + (extras.length ? "" : ' class="off"') + "><div>" + (extras.length ? "With " + extras.join(", ") + "." : "Plain build: no boot card, no version line.") + "</div></li>";
  h += with8
    ? "<li><div><strong>Restored animation frames</strong> from your arcade set (" + esc(state.arcade.message) + "), used when the machine has 8 MB of RAM. The image grows by about 28 MB.</div></li>"
    : '<li class="off"><div>Restored animation frames — add an arcade ROM set in step 2 to include them.</div></li>';
  h += "<li" + (exp ? "" : ' class="off"') + "><div>Output: <code>.bin</code> + <code>.cue</code>" + (exp ? '<br><span class="mono">expected SHA-1 ' + exp + "</span>" : '<br><span class="mono">no reference SHA-1 is recorded for this combination of options</span>') + "</div></li>";
  $("plan").innerHTML = h;
  // options that need code this page does not carry are switched off, with the reason
  $("opt-title").disabled = !state.options.title || with8;
  if (with8) $("opt-title").checked = true;
  $("opt-title-note").textContent = with8 ? "(always shown with restored frames)" : state.options.title ? "“" + state.options.title_text + "”" : "(needs the command-line builder)";
  $("opt-logo").disabled = !state.options.logo;
  if (state.ready && !state.options.logo) $("opt-logo").checked = false;
  if (state.ready && !state.options.title && !with8) $("opt-title").checked = false;
  $("opt-logo-note").textContent = state.options.logo ? "" : "(needs the command-line builder)";

  $("adv-note").textContent = "The defaults are the release configuration. Other texts and experimental switches are available in the command-line builder (builder/build.py).";
  const discOk = state.disc && state.disc.status === "ok";
  const arcOk = !state.arcadeFiles.length || (state.arcade && state.arcade.status === "ok");
  $("go").disabled = !(state.ready && discOk && arcOk) || state.building;
  $("go").textContent = with8 ? "Build the patched image (with restored frames)" : "Build the patched image";
  if (!state.building && !state.result) {
    if (discOk && arcOk && state.ready) status("st-build", "busy", with8 ? "Ready. This build takes several minutes and needs about 2.5 GB of free memory; the page stays responsive." : "Ready. The build takes a few minutes.");
    else if (!$("st-build").classList.contains("bad")) status("st-build", null);
  }
}
document.querySelectorAll("#adv input").forEach((i) => (i.onchange = () => { clearResult(); refresh(); }));

/* ------------------------------------------------------------------ building */
const STAGES = [["extract", "Reading the game files", 2], ["sprites", "Re-encoding the character graphics", 75], ["sound", "Rebuilding the sound banks", 10],
                ["arcade", "Restoring animation frames from the arcade set", 230],
                ["disc", "Assembling the patched disc", 3], ["digest", "Checksum of the result", 4]];
let run = null;                           // {stages: [{key, title, weight, frac, state, t0, t}], sub: counters}

function startBuild() {
  const with8 = withArcade();
  clearResult(); $("log").textContent = "";
  state.building = true; state.t0 = performance.now();
  run = { stages: STAGES.filter((s) => s[0] !== "arcade" || with8).map(([key, title, weight]) => ({ key, title, weight: key === "disc" && with8 ? 100 : weight, frac: 0, state: "", t0: 0, t: 0 })), packed: 0, chars: 0 };
  $("progress").hidden = false; $("cancel").hidden = false; status("st-build", null);
  drawProgress(); refresh();
  worker.postMessage({ type: "build", flags: flags() });
  run.timer = setInterval(drawProgress, 500);
}

function onProgress(m) {
  if (m.stage === "hash") { if (!state.disc) status("st-disc", "busy", "Checking " + esc(state.discFile.name) + " … " + Math.round(m.frac * 100) + " %"); return; }
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
    const t = s.state === "done" ? secs(s.t) : s.state === "run" ? secs((performance.now() - s.t0) / 1000) : "";
    return '<li class="' + s.state + '"><span class="dot"></span><span>' + esc(s.title) + (s.state === "run" && s.text ? " — " + esc(s.text) : "") + '</span><span class="t">' + t + "</span></li>";
  }).join("") + '<li class="run"><span></span><span class="t">elapsed ' + secs((performance.now() - state.t0) / 1000) + "</span><span></span></li>";
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
  endBuild(); run = null; $("progress").hidden = true;
  status("st-build", "warn", "Cancelled. Nothing was written.");
  state.disc = null; state.arcade = null;
  startWorker();                          // a fresh worker; the files are verified again when it is ready
  if (state.discFile) status("st-disc", "busy", "Checking " + esc(state.discFile.name) + " …");
}

function onDone(m) {
  if (run) { run.stages.forEach((s) => { if (s.state !== "done") { s.state = "done"; s.frac = 1; if (s.t0) s.t = (performance.now() - s.t0) / 1000; } }); drawProgress(); }
  endBuild();
  state.result = m;
  const binUrl = URL.createObjectURL(m.blob), cueUrl = URL.createObjectURL(new Blob([m.cue], { type: "text/plain" }));
  state.urls.push(binUrl, cueUrl);
  $("dl-bin").href = binUrl; $("dl-bin").download = m.name + ".bin";
  $("dl-cue").href = cueUrl; $("dl-cue").download = m.name + ".cue";
  const verdict = !m.expected ? "no reference recorded for these options"
    : m.expected === m.sha1 ? '<span class="match">✓ identical to the reference build</span>' : '<span class="nomatch">✗ differs from the reference build (' + m.expected + ") — please report this</span>";
  $("facts").innerHTML =
    "<dt>File</dt><dd><code>" + esc(m.name) + ".bin</code> + <code>" + esc(m.name) + ".cue</code> (" + mb(m.size) + ")</dd>" +
    "<dt>Contents</dt><dd>" + (m.variant === "8mb" ? "tag hack + restored frames (" + esc(m.arcadeSet) + ")" : "tag hack, 2 MB") + "</dd>" +
    '<dt>SHA-1</dt><dd><span class="mono">' + m.sha1 + "</span><br>" + verdict + "</dd>" +
    "<dt>Built in</dt><dd>" + secs((performance.now() - state.t0) / 1000) + " · " + mb(m.newBytes) + " of new data, the rest is your original image</dd>";
  $("note-8mb").hidden = m.variant !== "8mb";
  $("card-result").hidden = false;
  status("st-build", "ok", "✓ Done.");
  $("card-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
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
