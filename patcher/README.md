# patcher — the build in a web page

`index.html` is a single self-contained page: pick your disc image (and optionally your arcade ROM zip), the page
verifies it, runs **the real build** in the browser and hands back `.bin` + `.cue` (or both in one `.zip`).
Nothing is uploaded and the page carries no game data — only this project's code.

## Hosting

**What to publish: `index.html`, nothing else** (about 475 KB). It is self-contained except for the Python
runtime, which stays on its official CDN. The other files in `patcher/` (`src/`, `vendor/`, `tests/`, `make.py`)
are sources and need not be published, though publishing the whole folder does no harm (about 1 MB).

* Runtime: [Pyodide](https://pyodide.org) 0.25.1 (Python 3.11.3, numpy 1.26.4) from
  `https://cdn.jsdelivr.net/pyodide/v0.25.1/full/` — six files, 25 MB uncompressed (less on the wire), fetched by
  the visitor's browser once and then served from its cache. The version is pinned on purpose: the encoders are
  checked against this numpy. No other request leaves the page; the files a visitor picks are never sent anywhere.
* The page needs no server-side code, no special headers (no cross-origin isolation), and works under any path.
* It also works opened from disk (`file://`, double click), with internet access for the runtime.

Steps (GitHub Pages, from a branch that holds only the page):

    python patcher/make.py                      # 1. regenerate index.html from the current tools
    node patcher/tests/browser_test.cjs --disc ORIGINAL.bin        # 2. optional: build once in a real browser
    git worktree add --orphan -b gh-pages ../xvsf-pages            # 3. first time only: an empty branch next to the repo
    cp patcher/index.html ../xvsf-pages/index.html && touch ../xvsf-pages/.nojekyll
    cd ../xvsf-pages && git add index.html .nojekyll && git commit -m "Patcher page" && git push -u origin gh-pages
    # 4. on github.com: Settings -> Pages -> Source "Deploy from a branch" -> gh-pages, folder / (root)

The page is then at `https://<user>.github.io/<repository>/`. Notes: GitHub Pages serves from the root or from
`/docs` of a branch, which is why the page goes to its own branch instead of being served from `patcher/`; Pages
for a private repository needs a paid plan, and a published page is public even when the repository is not. Any
other static host works the same way: upload `index.html`.

Without the CDN (an intranet, an archive copy): download the six files of the CDN directory above (`pyodide.js`,
`pyodide.asm.js`, `pyodide.asm.wasm`, `python_stdlib.zip`, `pyodide-lock.json`,
`numpy-1.26.4-cp311-cp311-emscripten_3_1_46_wasm32.whl`) into `pyodide/` next to the page and build it with
`python patcher/make.py --pyodide ./pyodide/`. This variant has not been tested, and it cannot work from `file://`.

## Rebuilding the page

    python patcher/make.py            # src/ + the bundle -> index.html

`index.html` is generated; edit `src/`. The page must be rebuilt whenever `builder/` or `tools/` change, because
it contains them (the *bundle*: `builder/xvb`, `builder/data`, `tools/*.py`, `tools/ap`,
`tools/ap8`, `tools/logo`, and the prebuilt MIPS blobs of `tools/tagload` and `tools/nspdec`; about 210 KB).
See `builder/README.md`, "After the tools … change", for the blobs and reference hashes the page relies on.

## How it works

| file | role |
|---|---|
| `src/page.html`, `style.css`, `app.js` | the page: file choice, messages, progress, downloads. Main thread, no heavy work. |
| `src/worker.js` | Web Worker: loads Pyodide, unpacks the bundle, mounts the chosen files read-only (WORKERFS: read in slices, never copied to memory) and calls `builder/xvb/web.py` — the same `pipeline.run()` as the command line. |
| `src/kernels.js` | the encoders' hot loops in JavaScript, line by line the twin of `builder/xvb/kernels.py` (Pyodide has no numba). |
| `src/zopfli.js`, `vendor/zopfli/` | zopfli compiled to WebAssembly (npm `@gfx/zopfli` 1.0.15, Apache-2.0), used by the 8 MB build; gives the same bytes as the Python `zopfli` module. |

The result is not a copy of the image in memory: the pipeline returns "the original + these sectors", and the
worker builds a `Blob` out of slices of the user's own file and the new sectors. The browser streams it to disk on
download. The SHA-1 shown is computed over that result and compared with `builder/data/known.json`.

Cancel terminates the worker (the build is one long synchronous computation) and starts a fresh one.

## Supported input

* Disc: the raw `.bin` (MODE2/2352) of the USA release. A `.cue` dropped with it is ignored; it is not needed.
  CHD/PBP/ECM/2048-byte `.iso` are not read.
* Arcade: a zip of `xmvsf`, `xmvsfu`, or `xmvsfu1d` together with its parent.
* Options (Advanced): the defaults are the release configuration — boot card and version line on. Each can be
  switched off for the 2 MB build, and the stock button layout chosen. With an arcade set the boot card and the
  button layout can be changed; the version line is always shown (it carries the 8MB indicator). The expected SHA-1
  for the chosen combination is shown before building. Free version text and experimental switches need the
  command-line builder.
* Output names: `X-Men vs. Street Fighter (USA) [Tag Hack 1.0.1].bin` / `.cue`, or `… [Tag Hack 1.0.1 + Restored
  Frames]`; the `.cue` names its `.bin`. No CHD in the browser.

## Tests

    node patcher/tests/browser_test.cjs --disc DISC.bin [--arcade SET.zip] [--file-url]

drives a real Chrome over the DevTools protocol with real files: wrong-file messages, cancel, a full build, the
download and the zip, screenshots (default `work/patcher_shots/`), time and memory.
`patcher/tests/node_build.cjs` runs the same bundle and kernels under Node for quick iteration.
