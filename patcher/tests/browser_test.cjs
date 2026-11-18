/* Real-browser test of the patcher page: drives Chrome over the DevTools protocol (no dependencies,
 * Node 22+), with real files, and takes screenshots of the page states.
 *
 *   node patcher/tests/browser_test.cjs --disc DISC.bin [--arcade SET.zip[,PARENT.zip]] [--file-url] [--shots DIR]
 *        [--chrome PATH] [--headed] [--skip-errors] [--only-shots] [--tag NAME] [--set "CSS=0|1,..."] [--also-reject FILE,...]
 *        [--lang en|pt]   (page language for the run; the result is also shot in the other language)
 *
 *   default: serves patcher/ on http://127.0.0.1:<port>/ (as a static host would); --file-url opens
 *   patcher/index.html straight from disk instead.
 * Prints: time to ready, build time, peak memory of the browser's processes, SHA-1 shown by the page and
 * SHA-1 of the file the browser actually downloaded.
 */
const fs = require("fs"), path = require("path"), http = require("http"), os = require("os"), crypto = require("crypto");
const { spawn, execFileSync } = require("child_process");
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i < 0 ? d : (process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : true); };
const ROOT = path.join(__dirname, "..");
const SHOTS = path.resolve(arg("shots", path.join(ROOT, "..", "work", "patcher_shots")));
const TAG = arg("tag", arg("arcade") ? "8mb" : "2mb");
const CHROME = arg("chrome", ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/google-chrome"].find((p) => fs.existsSync(p)));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function serve() {
  const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".wasm": "application/wasm", ".json": "application/json", ".zip": "application/zip" };
  return new Promise((res) => {
    const srv = http.createServer((q, s) => {
      const f = path.join(ROOT, decodeURIComponent(q.url.split("?")[0]).replace(/^\/+/, "") || "index.html");
      if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { s.writeHead(404); return s.end(); }
      s.writeHead(200, { "content-type": types[path.extname(f)] || "application/octet-stream" }); fs.createReadStream(f).pipe(s);
    }).listen(0, "127.0.0.1", () => res(srv));
  });
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.wait = new Map(); this.handlers = [];
    ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id) { const w = this.wait.get(m.id); this.wait.delete(m.id); m.error ? w.rej(new Error(m.error.message)) : w.res(m.result); } else this.handlers.forEach((h) => h(m)); }; }
  send(method, params = {}) { return new Promise((res, rej) => { const id = ++this.id; this.wait.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params })); }); }
  async eval(expr) { const r = await this.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + JSON.stringify(r.exceptionDetails.exception)); return r.result.value; }
  async shot(name) { const r = await this.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); fs.writeFileSync(path.join(SHOTS, name + ".png"), Buffer.from(r.data, "base64")); console.log("  screenshot", name + ".png"); }
  async until(expr, ms, what) { const t0 = Date.now(); for (;;) { if (await this.eval(expr)) return (Date.now() - t0) / 1000; if (Date.now() - t0 > ms) throw new Error("timeout waiting for " + (what || expr)); await sleep(250); } }
  async setFiles(sel, files) { const { root } = await this.send("DOM.getDocument"); const { nodeId } = await this.send("DOM.querySelector", { nodeId: root.nodeId, selector: sel }); await this.send("DOM.setFileInputFiles", { nodeId, files }); }
}

function memory(marker) {
  // working set of every browser process started with our profile directory -> {total, largest} in MB
  try {
    const out = execFileSync("powershell", ["-NoProfile", "-Command",
      `Get-CimInstance Win32_Process -Filter "name='chrome.exe' or name='msedge.exe'" | Where-Object { $_.CommandLine -like '*${marker}*' } | ForEach-Object { $_.WorkingSetSize }`], { encoding: "utf8" });
    const v = out.split(/\s+/).filter(Boolean).map(Number);
    return { total: v.reduce((a, b) => a + b, 0) / 1048576, largest: Math.max(0, ...v) / 1048576 };
  } catch (e) { return { total: 0, largest: 0 }; }
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const disc = path.resolve(arg("disc")), arcade = arg("arcade") ? String(arg("arcade")).split(",").map((f) => path.resolve(f)) : null;   // a clone zip,its parent zip
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "xvsf_patcher_test_")), marker = path.basename(profile), dl = path.join(profile, "dl");
  fs.mkdirSync(dl);
  const srv = arg("file-url") ? null : await serve();
  const url = srv ? `http://127.0.0.1:${srv.address().port}/index.html` : "file:///" + path.join(ROOT, "index.html").replace(/\\/g, "/");
  const port = 9300 + Math.floor(Math.random() * 500);
  const chrome = spawn(CHROME, [arg("headed") ? "--start-maximized" : "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", "--window-size=1280,1000", "about:blank"], { stdio: "ignore" });
  let peak = { total: 0, largest: 0 };
  const sampler = setInterval(() => { const m = memory(marker); peak = { total: Math.max(peak.total, m.total), largest: Math.max(peak.largest, m.largest) }; }, 3000);
  try {
    let target = null;
    for (let i = 0; i < 60 && !target; i++) { await sleep(250); try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch (e) { /* not up yet */ } }
    const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
    const c = new CDP(ws);
    const errors = [];
    c.handlers.push((m) => { if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text); if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push(m.params.entry.text); });
    await c.send("Page.enable"); await c.send("Runtime.enable"); await c.send("Log.enable"); await c.send("DOM.enable");
    await c.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: dl });
    console.log("browser:", (await c.send("Browser.getVersion")).product, "| page:", url);
    const theme = (t) => c.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: t }] });
    await theme("light");
    const t0 = Date.now();
    await c.send("Page.navigate", { url });
    await c.until("document.readyState === 'complete' && !!document.getElementById('go')", 20000, "page load");
    await c.shot(TAG + "_01_loading");
    const ready = await c.until("document.getElementById('runtime').textContent === '' || document.getElementById('st-build').classList.contains('bad')", 180000, "runtime");
    if (await c.eval("document.getElementById('st-build').classList.contains('bad')")) throw new Error("page failed to start: " + (await c.eval("document.getElementById('st-build').textContent")));
    console.log("runtime ready after %ss (page load to builder ready)", ((Date.now() - t0) / 1000).toFixed(1));
    const lang = (l) => c.eval(`(() => { if (LANG !== ${JSON.stringify(l)}) document.getElementById("lang").click(); return LANG; })()`);
    if (arg("lang")) console.log("language:", await lang(String(arg("lang"))));
    await c.shot(TAG + "_02_ready_light");
    await theme("dark"); await sleep(300); await c.shot(TAG + "_03_ready_dark"); await theme("light");

    if (!arg("skip-errors")) {                           // friendly messages for wrong files
      const junk = path.join(profile, "not_a_disc.bin"); fs.writeFileSync(junk, crypto.randomBytes(2352 * 40));
      await c.setFiles("#in-disc", [junk]);
      await c.until("document.getElementById('st-disc').classList.contains('bad')", 60000, "junk verdict");
      console.log("wrong file  ->", await c.eval("document.getElementById('st-disc').innerText"));
      await c.shot(TAG + "_04_wrong_file");
      await c.setFiles("#in-arcade", [junk]);
      await c.until("document.getElementById('st-arcade').classList.contains('bad')", 60000, "junk arcade verdict");
      console.log("wrong zip   ->", await c.eval("document.getElementById('st-arcade').innerText"));
      await c.shot(TAG + "_05_wrong_arcade");
      await c.eval("document.getElementById('arc-clear').click()");
      for (const extra of String(arg("also-reject", "")).split(",").filter(Boolean)) {      // e.g. an already patched image, another region
        await c.setFiles("#in-disc", [path.resolve(extra)]);
        await c.until("['bad','ok','warn'].some((k) => document.getElementById('st-disc').classList.contains(k))", 120000, "verdict");
        console.log(path.basename(extra), "->", await c.eval("document.getElementById('st-disc').innerText + ' [' + ((state.disc && state.disc.error) || '') + ' file size ' + (state.discFile && state.discFile.size) + ']'"));
        await c.shot(TAG + "_06_rejected_" + path.basename(extra).replace(/\W+/g, "_").slice(0, 24));
      }
    }

    let t = Date.now();
    await c.setFiles("#in-disc", [disc]);
    await c.until("document.getElementById('st-disc').classList.contains('ok')", 180000, "disc verified");
    console.log("disc verified in %ss:", ((Date.now() - t) / 1000).toFixed(1), (await c.eval("document.getElementById('st-disc').innerText")).replace(/\n/g, " | "));
    if (arcade) {
      await c.setFiles("#in-arcade", arcade);
      await c.until("document.getElementById('st-arcade').classList.contains('ok')", 120000, "arcade recognised");
      console.log("arcade:", await c.eval("document.getElementById('st-arcade').innerText"));
    }
    await c.eval("document.getElementById('adv') && (document.getElementById('adv').open = true)");     // (1.3 final: no options)
    await c.shot(TAG + "_07_verified");
    if (arg("only-shots")) return;

    if (!arg("skip-errors")) {                           // cancel, then build for real
      await c.eval("document.getElementById('go').click()"); await sleep(6000);
      await c.shot(TAG + "_08_building_early");
      await c.eval("document.getElementById('cancel').click()"); await sleep(500);
      await c.shot(TAG + "_09_cancelled");
      await c.until("document.getElementById('st-disc').classList.contains('ok') && !document.getElementById('go').disabled", 240000, "ready again after cancel");
      console.log("cancel: worker restarted, files verified again");
    }
    // --set "#opt-logo=0,#opt-title=0,input[value=stock]=1": options to change before the build
    for (const f of String(arg("set", "")).split(",").filter(Boolean)) {
      const [sel, v] = f.split(/=(?=[01]$)/);
      await c.eval(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (e.disabled) throw new Error("option is disabled: " + ${JSON.stringify(sel)}); e.checked = ${v === "1"}; e.onchange && e.onchange(); })()`);
    }
    console.log("plan:", (await c.eval("document.getElementById('plan').innerText")).replace(/\n+/g, " | "));
    t = Date.now();
    await c.eval("document.getElementById('go').click()");
    let shotMid = false;
    for (;;) {
      await sleep(1000);
      const st = await c.eval("JSON.stringify({done: !document.getElementById('card-result').hidden, bad: document.getElementById('st-build').classList.contains('bad'), text: document.getElementById('st-build').innerText, run: (document.querySelector('#stages li.run') || {}).innerText || ''})");
      const s = JSON.parse(st);
      if (errors.length) throw new Error("page error during the build: " + errors.slice(0, 3).join(" | "));
      if (s.bad) throw new Error("build failed: " + s.text + "\n" + (await c.eval("document.getElementById('log').textContent.slice(-3000)")));
      if (!shotMid && (Date.now() - t) > 25000) { shotMid = true; await c.shot(TAG + "_10_building"); await c.send("Emulation.setDeviceMetricsOverride", { width: 420, height: 900, deviceScaleFactor: 1, mobile: false }); await sleep(300); await c.shot(TAG + "_11_building_narrow"); await c.send("Emulation.clearDeviceMetricsOverride"); }
      if (s.done) break;
      if (Date.now() - t > 3600e3) throw new Error("build timeout");
    }
    const buildSecs = (Date.now() - t) / 1000;
    console.log("BUILD TIME (click to result): %ss", buildSecs.toFixed(1));
    console.log("page says:", (await c.eval("document.getElementById('facts').innerText")).replace(/\n+/g, " | "));
    console.log("stage times:", await c.eval("JSON.stringify(state.result.times)"), "| WebAssembly memory of the worker:", await c.eval("state.result.heapMB"), "MB");
    console.log("memory when the build finished (before any download): all processes %s MB, largest %s MB", peak.total.toFixed(0), peak.largest.toFixed(0));
    await c.shot(TAG + "_12_done");
    await theme("dark"); await sleep(300); await c.shot(TAG + "_13_done_dark"); await theme("light");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 420, height: 900, deviceScaleFactor: 1, mobile: false }); await sleep(300); await c.shot(TAG + "_14_done_narrow"); await c.send("Emulation.clearDeviceMetricsOverride");
    if (arg("lang")) {                                   // the other language on the finished page: texts only, the result stays
      const other = String(arg("lang")) === "pt" ? "en" : "pt", sha0 = await c.eval("state.result.sha1");
      await lang(other); await sleep(300); await c.shot(TAG + "_15_done_" + other);
      console.log("after switching to %s: facts %s | sha1 unchanged %s", other, (await c.eval("document.getElementById('facts').innerText")).split("\n").filter(Boolean).join(" | "), (await c.eval("state.result.sha1")) === sha0);
      await lang(String(arg("lang")));
    }
    const shown = await c.eval("state.result.sha1"), name = await c.eval("state.result.name"), size = await c.eval("state.result.size");
    // the download itself: the browser writes the Blob (slices of the input + new sectors) to disk
    t = Date.now();
    await c.eval("document.getElementById('dl-bin').click()");
    const out = path.join(dl, name + ".bin");
    for (;;) { await sleep(500); if (fs.existsSync(out) && fs.statSync(out).size === size && !fs.readdirSync(dl).some((f) => f.endsWith(".crdownload"))) break; if (Date.now() - t > 600e3) throw new Error("download timeout"); }
    console.log("download of %s bytes took %ss", size, ((Date.now() - t) / 1000).toFixed(1));
    const h = crypto.createHash("sha1"); await new Promise((r) => fs.createReadStream(out).on("data", (d) => h.update(d)).on("end", r));
    const got = h.digest("hex");
    console.log("SHA-1 shown by the page :", shown);
    console.log("SHA-1 of the downloaded :", got, got === shown ? "(same)" : "*** DIFFERENT ***");
    await c.eval("document.getElementById('dl-zip').click()");
    const zip = path.join(dl, name + ".zip");
    for (t = Date.now(); ;) { await sleep(500); if (fs.existsSync(zip) && fs.statSync(zip).size > size && !fs.readdirSync(dl).some((f) => f.endsWith(".crdownload"))) break; if (Date.now() - t > 600e3) throw new Error("zip download timeout"); }
    try { const l = execFileSync("python", ["-c", "import zipfile,sys,hashlib\nz=zipfile.ZipFile(sys.argv[1]); print(z.testzip(), [(i.filename, i.file_size) for i in z.infolist()], hashlib.sha1(z.read(z.infolist()[1])).hexdigest())", zip], { encoding: "utf8" }); console.log("zip check (testzip, entries, sha1 of the .bin inside):", l.trim()); } catch (e) { console.log("zip check failed:", e.message); }
    const m = memory(marker); peak = { total: Math.max(peak.total, m.total), largest: Math.max(peak.largest, m.largest) };
    console.log("PEAK MEMORY (working set, sampled every 3 s): all browser processes %s MB, largest single process %s MB", peak.total.toFixed(0), peak.largest.toFixed(0));
    if (errors.length) console.log("console errors:", errors.slice(0, 5));
  } finally {
    clearInterval(sampler);
    chrome.kill(); if (srv) srv.close();
    await sleep(800); try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* browser still closing */ }
  }
})().catch((e) => { console.error("TEST FAILED:", e.message); process.exit(1); });
