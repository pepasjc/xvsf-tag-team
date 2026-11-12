#!/usr/bin/env python3
"""Build the patcher page:  python patcher/make.py     ->  patcher/index.html  (one self-contained file)

index.html carries everything except the Pyodide runtime: the page (src/page.html, style.css, app.js),
the worker (src/kernels.js + src/worker.js, started from a Blob so that it also works from file://)
and the BUNDLE - a zip of the build pipeline (builder/xvb, builder/data) and of the
project's tools (tools/*.py, their prebuilt MIPS blobs, tools/ap, tools/ap8), base64-encoded.
The bundle contains code and measurement tables only; no game data.

    --pyodide URL   where the page loads Pyodide from (default: the pinned official CDN build).
                    For a host without internet access put a copy of that directory next to index.html
                    and pass e.g. --pyodide ./pyodide/   (see README.md)
    --bundle-only   write patcher/xvsf_bundle.zip and stop (the Node test harness uses it)
"""
import argparse, base64, hashlib, io, json, os, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, ".."))
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.25.1/full/"       # Python 3.11.3, numpy 1.26.4
SHOW = ("What it does", "Restored frames (8 MB)", "Known issues", "How it works")      # README.md sections shown on the page


def bundle_files():
    """(archive name, path on disk), sorted: the archive is reproducible"""
    out = []

    def add(rel, keep=lambda f: True):
        d = os.path.join(REPO, *rel.split("/"))
        if not os.path.isdir(d): return
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if os.path.isfile(p) and keep(f): out.append((rel + "/" + f, p))
    py = lambda f: f.endswith(".py")
    add("builder/xvb", py)
    add("builder/data", lambda f: f.endswith(".json")); add("builder/data/toolcache", lambda f: f.endswith(".json"))
    add("tools", lambda f: py(f) and not f.startswith("cold"))
    add("tools/ap", py)
    add("tools/ap8", lambda f: f.endswith((".c", ".S", ".h", ".ld")))
    add("tools/logo")
    add("tools/tagload", lambda f: f.endswith(".sym") or (f.endswith(".bin") and f.startswith("tagload.") and ".tab" not in f))
    add("tools/nspdec", lambda f: f in ("nspdec.bin", "nspdec.sym"))
    return out


def make_bundle():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in bundle_files():
            zi = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)); zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, open(path, "rb").read())
    return buf.getvalue()


def readme_sections(md):
    """the sections of README.md the page shows -> {title: [paragraph or bullet text, ...]}"""
    out = {}; cur = None; new = True
    for line in md.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip(); out[cur] = []; new = True
        elif cur is None or line.startswith("|"): continue
        elif not line.strip(): new = True
        elif line.startswith("- "): out[cur].append(line[2:].strip()); new = False
        elif new: out[cur].append(line.strip()); new = False
        else: out[cur][-1] += " " + line.strip()                   # continuation of a wrapped line
    return {k: out[k] for k in SHOW if k in out}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pyodide", default=PYODIDE); ap.add_argument("--bundle-only", action="store_true")
    a = ap.parse_args()
    bundle = make_bundle()
    print("bundle: %d files, %d bytes, sha1 %s" % (len(bundle_files()), len(bundle), hashlib.sha1(bundle).hexdigest()))
    if a.bundle_only:
        open(os.path.join(HERE, "xvsf_bundle.zip"), "wb").write(bundle); return
    src = lambda n: open(os.path.join(HERE, "src", n), encoding="utf-8").read()
    known = json.load(open(os.path.join(REPO, "builder", "data", "known.json")))
    cfg = dict(pyodide=a.pyodide if a.pyodide.endswith("/") else a.pyodide + "/", known=known,
               readme=readme_sections(open(os.path.join(REPO, "README.md"), encoding="utf-8").read()),
               bundle_sha1=hashlib.sha1(bundle).hexdigest())
    worker = src("kernels.js") + "\n" + src("zopfli.js") + "\n" + src("worker.js")
    vz = os.path.join(HERE, "vendor", "zopfli")                # zopfli compiled to WebAssembly (Apache-2.0), for the 8 MB build
    zopfli = dict(glue=open(os.path.join(vz, "libzopfli.js"), encoding="utf-8").read(), wasm=json.load(open(os.path.join(vz, "libzopfli-wasm.json"))))
    page = src("page.html")
    rep = {"/*{{STYLE}}*/": src("style.css"), "/*{{APP}}*/": src("app.js"),
           "{{WORKER}}": base64.b64encode(worker.encode()).decode(), "{{BUNDLE}}": base64.b64encode(bundle).decode(),
           "{{CONFIG}}": json.dumps(cfg).replace("</", "<\\/"), "{{ZOPFLI}}": json.dumps(zopfli).replace("</", "<\\/")}
    for k, v in rep.items():
        assert page.count(k) == 1, k
        page = page.replace(k, v)
    out = os.path.join(HERE, "index.html")
    open(out, "w", encoding="utf-8", newline="\n").write(page)
    print("wrote %s (%d bytes); Pyodide from %s" % (out, len(page.encode()), cfg["pyodide"]))


if __name__ == "__main__":
    main()
