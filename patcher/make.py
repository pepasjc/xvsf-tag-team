#!/usr/bin/env python3
"""Build the patcher page:  python patcher/make.py     ->  patcher/index.html  (one self-contained file)

index.html carries everything except the Pyodide runtime: the page (src/page.html, style.css, app.js),
the worker (src/kernels.js + src/worker.js, started from a Blob so that it also works from file://)
and the BUNDLE - a zip of the build pipeline (builder/xvb, builder/data incl. the prebaked MIPS blobs
builder/data/blobs) and of the project's tools (tools/*.py, tools/speed/*.py, tools/ap), base64-encoded.
The bundle contains code and measurement tables only; no game data.

    --pyodide URL   where the page loads Pyodide from (default: the pinned official CDN build).
                    For a host without internet access put a copy of that directory next to index.html
                    and pass e.g. --pyodide ./pyodide/   (see README.md)
    --bundle-only   write patcher/xvsf_bundle.zip and stop (the Node test harness uses it)
"""
import argparse, base64, hashlib, io, json, os, re, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, ".."))
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.25.1/full/"       # Python 3.11.3, numpy 1.26.4
SHOW = ("What the hack does", "Restored animation frames (optional, 8 MB)", "Known issues", "How it fits in 2 MB", "Legal")      # the side panel's keys (src/app.js)
# public repository: the X-Men vs. Street Fighter texts come from docs/xvsf/README.md (section -> the page's key), the
# legal line from the README's License section
XVSF_DOC = "docs/xvsf/README.md"
XVSF_MAP = {"What it does": "What the hack does", "Restored frames (8 MB)": "Restored animation frames (optional, 8 MB)",
            "Known issues": "Known issues"}
LEGAL = ("A free fan project, not affiliated with or endorsed by Capcom or Marvel. X-Men vs. Street Fighter and Marvel Super "
         "Heroes vs. Street Fighter are © Capcom; Marvel characters © Marvel. Use it only with a disc and an arcade ROM set you own.")


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
    add("builder/data", lambda f: f.endswith(".json"))
    add("builder/data/blobs", lambda f: f.endswith((".json", ".bin")))      # ALL of our MIPS code, prebaked (the page compiles nothing)
    add("tools", lambda f: py(f) and not f.startswith("cold"))
    add("tools/speed", py)                       # speedpatch.py + frame.py are imported (their results come from the blobs)
    add("tools/ap", py)
    add("tools/snd", py)                         # 1.2 sound banks: VAB editing, resampler, ADPCM encoder (hot loops: src/kernels.js)
    add("tools/ach", lambda f: f in ("xvach.py", "achbuild.py", "setc.py"))   # 1.3: built-in achievements (xvach.code comes from the blobs)
    add("tools/ach/xvsf", lambda f: f == "set.py")   # (xvach reads the set at import)
    add("tools/ap8", lambda f: f == "hot8.json")  # data: the 8 MB pre-decode order (read by tools/mkap8disc.py)
    add("tools/logo", lambda f: f.endswith(".bin"))   # card2.bin: the second card's own layer (composed with the user's portraits)
    out.append(("builder/games.py", os.path.join(REPO, "builder", "games.py")))     # which game is this disc
    # MSHvSF: the builder and the tools it runs (the same file list as the command line's tool root, builder/mshb/pipeline.py)
    import sys
    sys.path.insert(0, os.path.join(REPO, "builder"))
    from mshb import pipeline as msh
    have = {n for n, p in out}
    out += [(n, p) for n, p in msh.root_files() if n not in have]
    out += [("builder/data/mshvsf/blobs/" + f, os.path.join(msh.BLOBS, f)) for f in sorted(os.listdir(msh.BLOBS)) if f.endswith(".json")]
    return sorted(set(out))


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
    return out


def page_readme():
    """the side panel's X-Men vs. Street Fighter sections, under the keys src/app.js reads"""
    sec = readme_sections(open(os.path.join(REPO, *XVSF_DOC.split("/")), encoding="utf-8").read())
    link = lambda t: re.sub(r"\[([^\]]+)\]\([^)]+\)", lambda mo: mo.group(1), re.sub(r"\s*\[(Details|The list)\]\([^)]+\)\.?", "", t))        # the page shows no links: [text](url) -> text
    out = {XVSF_MAP[k]: [link(t) for t in v] for k, v in sec.items() if k in XVSF_MAP}
    rf = "Restored animation frames (optional, 8 MB)"
    if rf in out: out[rf] = [""] + out[rf]          # app.js skips the section's first paragraph (the intro in the private README)
    out["Legal"] = [LEGAL]
    return {k: out[k] for k in SHOW if k in out}


def about_sections(md):
    """patcher/src/mshvsf.md -> {"intro": {title: [item, ...]}, "mshvsf": {...}}  (headings "## key: Title")"""
    out = {}; cur = None
    for line in md.splitlines():
        if line.startswith("## "):
            k, t = line[3:].split(":", 1); cur = out.setdefault(k.strip(), {}).setdefault(t.strip(), [])
        elif line.startswith("- ") and cur is not None: cur.append(line[2:].strip())
        elif line.strip() and cur is not None and cur: cur[-1] += " " + line.strip()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pyodide", default=PYODIDE); ap.add_argument("--bundle-only", action="store_true")
    a = ap.parse_args()
    bundle = make_bundle()
    print("bundle: %d files, %d bytes, sha1 %s" % (len(bundle_files()), len(bundle), hashlib.sha1(bundle).hexdigest()))
    if a.bundle_only:
        open(os.path.join(HERE, "xvsf_bundle.zip"), "wb").write(bundle); return
    src = lambda n: open(os.path.join(HERE, "src", n), encoding="utf-8").read()
    known = dict(xvsf=json.load(open(os.path.join(REPO, "builder", "data", "known.json"))),
                 mshvsf=json.load(open(os.path.join(REPO, "builder", "data", "mshvsf", "known.json"))))
    cfg = dict(pyodide=a.pyodide if a.pyodide.endswith("/") else a.pyodide + "/", known=known,
               readme=page_readme(),
               bundle_sha1=hashlib.sha1(bundle).hexdigest(), about=about_sections(open(os.path.join(HERE, "src", "mshvsf.md"), encoding="utf-8").read()),
               about_pt=about_sections(open(os.path.join(HERE, "src", "about_pt.md"), encoding="utf-8").read()))      # PT-BR side panel (src/i18n.js: the other texts)
    worker = src("kernels.js") + "\n" + src("kernels_msh.js") + "\n" + src("zopfli.js") + "\n" + src("worker.js")
    vz = os.path.join(HERE, "vendor", "zopfli")                # zopfli compiled to WebAssembly (Apache-2.0), for the 8 MB build
    zopfli = dict(glue=open(os.path.join(vz, "libzopfli.js"), encoding="utf-8").read(), wasm=json.load(open(os.path.join(vz, "libzopfli-wasm.json"))))
    page = src("page.html")
    rep = {"/*{{STYLE}}*/": src("style.css"), "/*{{APP}}*/": src("i18n.js") + chr(10) + src("app.js"),
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
