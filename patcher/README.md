# patcher — the build in a web page

Language: English or Brazilian Portuguese (`src/i18n.js`, PT side panel `src/about_pt.md`): the browser's language
picks it (pt* -> PT-BR), the button in the header switches, and the choice is kept in localStorage. Only texts change.

`index.html` is a single self-contained page: pick your disc image (and optionally your arcade ROM zip), the page
recognises the game, verifies the dump, runs **the real build** in the browser and hands back `.bin` + `.cue` (or both
in one `.zip`).  Games: X-Men vs. Street Fighter (USA, SLUS-00627; `builder/xvb`) and Marvel Super Heroes vs. Street
Fighter (USA, SLUS-00793; `builder/mshb`).  Which game: `builder/games.py` (the files on the disc; the release from the
boot file in SYSTEM.CNF; the dump by the SHA-1 of the whole image, hashed only for a supported release).  Marvel vs.
Capcom (SLUS-01059) is recognised and refused ("in progress"); a new game plugs in as a builder package with a
`web.py` (identify / check_arcade / sound_plan / build / result_*), an entry in `games.GAMES`, and its options in
`src/app.js` / `src/page.html`.
Nothing is uploaded and the page carries no game graphics, sound or code — only this project's code. Where a
rewritten routine keeps some of the game's original instructions, the page holds a reference instead and fills the
words in from the user's own disc (`builder/xvb/gameref.py`).

## Hosting

**What to publish: `index.html`, nothing else** (about 1.2 MB with both games). It is self-contained except for the Python
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
it contains them (the *bundle*: `builder/xvb`, `builder/data` with all of our MIPS code prebaked in
`builder/data/blobs`, `tools/*.py`, `tools/speed/*.py`, `tools/ap`, `tools/snd/*.py`, `tools/ap8/hot8.json`,
`tools/logo/*.bin`).
The page compiles nothing. `work/release12/record.py` bakes the blobs, records the reference hashes and runs
`make.py`; see `builder/README.md`, "After the tools … change".

## How it works

| file | role |
|---|---|
| `src/page.html`, `style.css`, `app.js` | the page: file choice, messages, progress, downloads. Main thread, no heavy work. |
| `src/worker.js` | Web Worker: loads Pyodide, unpacks the bundle, mounts the chosen files read-only (WORKERFS: read in slices, never copied to memory) and calls `builder/xvb/web.py` — the same `pipeline.run()` as the command line. |
| `src/kernels.js` | the encoders' hot loops in JavaScript, line by line the twin of `builder/xvb/kernels.py` (Pyodide has no numba), and of the sound kernels of `tools/snd/adpcm.py` / `resample.py` (`snd_*`). |
| `src/zopfli.js`, `vendor/zopfli/` | zopfli compiled to WebAssembly (npm `@gfx/zopfli` 1.0.15, Apache-2.0), used by the 8 MB build; gives the same bytes as the Python `zopfli` module. |

The result is not a copy of the image in memory: the pipeline returns "the original + these sectors", and the
worker builds a `Blob` out of slices of the user's own file and the new sectors. The browser streams it to disk on
download. The SHA-1 shown is computed over that result and compared with `builder/data/known.json`.

Sound banks (1.2): the ADPCM encoder jobs do not depend on each other. Before the build the worker asks Python for
all of them (`web.sound_plan`), hands them to up to four sub-workers (the same worker script, started from
`self.location`) and encodes the sprites meanwhile; the results go into a memo that the build's encoder reads by the
SHA-1 of its input (`web.sound_results`). Jobs that were not planned are encoded in place. The bytes are the same
either way, and the same as the command-line build's.

Cancel terminates the worker (and its sub-workers) (the build is one long synchronous computation) and starts a fresh one.

## Supported input

MSHvSF: the raw `.bin` of the USA release (SLUS-00793, 552,894,048 bytes, SHA-1 `6e50ac0d…`); arcade: `mshvsf.zip`,
or a clone zip (`mshvsfu`, …) together with `mshvsf.zip` (sets identified by their program ROMs,
`builder/data/mshvsf/arcade_sets.json`; every set gives the same restored frames here).  No options: the release image
(boot cards, speed meter in OPTION MODE off at boot, built-in achievements), with the 8 MB loader + restored frames
when an arcade set is given; the 8 MB loader without a set, meter on at boot and no boot cards are command-line only.  The build runs its long jobs in sub-workers: the sprite tiers (207 jobs, each sub-worker loads
its own Pyodide), the sound levels (one character's bank per job) and the 8 MB arcade frames (one job), all in up to
five Python sub-workers.  Measured in Chrome 157 (16 cores, 2026-11-16): 2 MB build 298 s, peak about 2.4 GB for all
browser processes; 8 MB build (mshvsfu + mshvsf) 304 s, peak about 2.9 GB: have about 3 GB free.  Both images are
bit-identical to the command-line builds (timings measured on a development build; the 1.0 release images are
`753e7b13…` and, with an arcade set, `e40f9fc4…`).  The same page still builds X-Men vs. Street
Fighter exactly as before (2 MB 113 s, 8 MB xmvsfu 332 s, hashes unchanged).
`patcher/tests/node_msh_build.cjs` runs the MSHvSF page path under Node (jobs one after the other).

X-Men vs. Street Fighter:

* Disc: the raw `.bin` (MODE2/2352) of the USA release. A `.cue` dropped with it is ignored; it is not needed.
  CHD/PBP/ECM/2048-byte `.iso` are not read.
* Arcade: a zip of `xmvsf`, `xmvsfu`, or `xmvsfu1d` together with its parent.
* No options: the page always builds the release image (boot card, version line, built-in achievements; 8 MB
  with restored frames when an arcade set is given). Its expected SHA-1 is shown before building and compared with
  the result. Every other variant (no boot card, stock buttons, no version line, plain, no achievements, 1.0.1 / 1.1)
  is built with the command-line builder.
* Memory and time (Chrome, measured for 1.2): the 2 MB build about 2 minutes, peak about 1.4 GB for all browser
  processes; the 8 MB build about 5-6 minutes, peak about 2.0 GB (worker 700 MB of WebAssembly memory plus the sound
  sub-workers): have about 2.5 GB free for it.
* Output names: `X-Men vs. Street Fighter (USA) [Tag Hack 1.3].bin` / `.cue`, or `… [Tag Hack 1.3 + Restored
  Frames]`; the `.cue` names its `.bin`. No CHD in the browser.

## Tests

    node patcher/tests/browser_test.cjs --disc DISC.bin [--arcade SET.zip] [--file-url]

drives a real Chrome over the DevTools protocol with real files: wrong-file messages, cancel, a full build, the
download and the zip, screenshots (default `work/patcher_shots/`), time and memory.
`patcher/tests/node_build.cjs` runs the same bundle and kernels under Node for quick iteration (`SND_PLAN=1`: the
page's sound path, plan + memo, with the jobs run one after the other).
