/* Shared hooks of the Node build harnesses (node_build.cjs, node_msh_build.cjs, node_mvc_build.cjs) for the release gate
 * (tools/release_gate.py):
 *   XVSF_BUNDLE=PATH   use this bundle zip instead of patcher/xvsf_bundle.zip (the gate passes the bundle it took out of
 *                      the page under test, so the run is on exactly that page's bytes)
 *   PROBE_MISSING=1    record every path under /xvsf (the bundle) that the Python side looked for and did not find
 *                      (os.stat: exists / isfile / isdir / getsize, and open); printed at exit as one line
 *                      "PROBE_MISSING <json list>" (only paths still missing when the build ends: files a stage generates
 *                      later are not reported).  A silent fallback on a file that the bundle forgot shows up here.
 */
const path = require("path");

exports.bundlePath = (testsDir) => process.env.XVSF_BUNDLE || path.join(testsDir, "..", "xvsf_bundle.zip");

exports.install = (py) => {
  if (!process.env.PROBE_MISSING) return;
  py.runPython(`
import os, builtins
_gate_miss = set()
def _gate_note(p):
    try:
        s = os.fsdecode(p) if not isinstance(p, int) else ""
    except Exception:
        return
    if s.startswith("/xvsf/"): _gate_miss.add(os.path.normpath(s))
_gate_stat, _gate_open = os.stat, builtins.open
def _gate_stat_w(p, *a, **k):
    try: return _gate_stat(p, *a, **k)
    except FileNotFoundError:
        _gate_note(p); raise
def _gate_open_w(p, *a, **k):
    try: return _gate_open(p, *a, **k)
    except FileNotFoundError:
        _gate_note(p); raise
os.stat = _gate_stat_w
builtins.open = _gate_open_w
`);
  process.on("exit", () => {
    try { console.log("PROBE_MISSING " + py.runPython("import json, os; json.dumps(sorted(p for p in list(_gate_miss) if not os.path.exists(p)))")); }
    catch (e) { console.log("PROBE_MISSING_ERROR " + e.message); }
  });
};
