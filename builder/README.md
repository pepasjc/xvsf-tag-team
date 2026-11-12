# builder — one command from your disc image to the patched image

    python builder/build.py --disc "path/to/original.bin" --out OUTDIR
    python builder/build.py --disc original.bin --arcade xmvsfu.zip --out OUTDIR

The first form builds the 2 MB tag hack. With `--arcade` (your own arcade ROM set; a clone zip followed by
its parent zip) the image also carries the restored animation frames for 8 MB setups. Output:
`OUTDIR/X-Men vs. Street Fighter (USA) [Tag Hack 1.0].bin` + `.cue` (`… [Tag Hack 1.0 + Restored Frames]` with an
arcade set; `--name` changes it), `build.log`, and a `.chd` with `--chd` when `chdman` is found (`XVSF_CHDMAN`,
PATH, `--chdman PATH`).

The default is the **release configuration**: boot card + version line on the main menu.

| options | 2 MB | with `--arcade` |
|---|---|---|
| (none) | boot card + version line (`--logo --title`) | boot card (`--logo`); the 8 MB loader always draws the version line |
| `--no-logo` | version line only | no boot card |
| `--no-menu-version` | boot card only | refused: the line carries the 8MB indicator |
| `--plain` | neither: the plain regression reference | no boot card: the plain 8 MB reference |
| `--buttons stock` | the game's own shoulder layout (`--nopad`) | the same (`--nopad`, handed on to the 2 MB build inside) |

Requirements: Python 3.11, `numpy`, `numba`. For `--arcade`: the `zopfli` Python module (without it
`tools/mkap8disc.py` falls back to zlib and the image differs from the reference). No compiler and no fixed paths
for these configurations. `python builder/build.py --help` lists the options.

## What it does

| stage | input | output (work directory) |
|---|---|---|
| verify | the image | SHA-1 and size against `data/known.json`; anything else is refused, with the reason (already patched, other region, not this game, not a raw image, altered dump) |
| extract | the image | `files/…` (every file up to 8 MB), `lba_map.json` |
| sprites | `files/A/A0/SP_PLxx.NSP`, `A2/SP_EFF1.NSP`, `data/tiles_*.json` | `build/nspm` (base, XVM1), `build/nsp` (strong, XVH1), `build/nspm4` (mid), `build/nspfat2` (fat), `build/nspm_eff` |
| arcade (only with `--arcade`) | the ROM zip(s), the image | `ap8content_base/` — `tools/ap/build8.py --direct --shared`; then `ap8content/` — `tools/ap/sel2build.py --base ap8content_base` (second select-screen sprite set) |
| disc | all of the above, `tools/` blobs | the patched image: `tools/mktagdisc.py`, or `tools/mkap8disc.py` (which runs the former inside) |
| seal | | EDC/ECC of every rewritten sector, in one vectorised pass |

Encoder parameters (recovered by matching the hand-made files byte for byte): base/mid/fat = XVM1 with 48 tables,
run penalty 8, model threshold 32 (`XVM_MB=32`); mid keeps the tiles of `tiles_mid.json` as stock RLE, fat the
union of `tiles_mid.json` and `tiles_fat.json`; a character with an empty mid list has mid = base; effects file =
XVM1 with 16 tables; strong = XVH1 with 256 tables and 256 classes.

The disc stages **run the project's own tools unmodified** (`xvb/pipeline.py`, class `Tools`): their path
constants are pointed at the work directory, the output image they open is a copy-on-write overlay of the input
(`xvb/cdrom.py`; no 400 MB copy, no whole image in memory), and their per-sector EDC/ECC is deferred. The mapping from the
builder's options to the tools' flags is `pipeline.tool_flags()` (shared with the web page); `--tool-flag X` hands
a flag through as it is. External programs are found by `tools/toolenv.py`.

The sprite encoders are ports of the project's first, standalone encoders (not in this repository) (`xvb/xvm1.py`, `xvb/xvh1.py`)
onto batched kernels (`xvb/kernels.py`: one call per file and pass). The same kernels exist in JavaScript for
the browser patcher (`patcher/src/kernels.js`). Two things in them are there for reproducibility, not speed:

* `argsort_np` is numpy's scalar introsort, spelled out. The clustering depends on the order `np.argsort`
  gives to *equal* keys; that order differs between numpy builds (SIMD sorts), and a stable sort gives other
  files than the reference.
* `cost_argmin` replaces a dense float matrix product by exact integer sums over the non-zero entries.

## Data in this directory

* `data/tiles_mid.json`, `data/tiles_fat.json` — tile numbers per character (measurement results: which tiles
  are decoded in bursts). Their generators need emulator measurement logs and are not part of this
  repository.
* `data/known.json` — SHA-1/size of the accepted input, and the SHA-1 of the output for the option
  combinations that were built here (`--record-expected`).
* `data/toolcache/*.json` — recorded results of the three functions in `tools/` that run the MIPS compiler
  (`mkap8disc.build`, `titlepatch.build`, `logopatch.build`), keyed by their arguments and source files. With a
  hit no compiler is needed; with a miss the compiler `tools/toolenv.py` finds is used (`XVSF_MIPS_PREFIX` or
  `--mips-prefix`, PATH, the development default) and `--record-blobs` stores the result. Our own code only
  (the logo blob includes the boot card bitmap, `tools/logo/card.bin`).

Nothing here is derived from the game or the arcade ROMs.

## After the tools or the arcade content builder change

The 8 MB loader no longer depends on the content: the memory map (`arena`, `arena_end`, `slotarea`) is written into
the module table by `tools/mkap8disc.py`, so one recorded blob (`mkap8disc.build(symbols, version text)`) serves every
arcade set and every content revision. New blobs are needed only when `tools/ap8/`, `tools/logo/` or
`tools/logopatch.py` / `tools/titlepatch.py` change (or for another version text); new reference hashes whenever the
tools or the content builder change. On a machine with the compiler:

    for each arcade set:  python builder/build.py --disc … --arcade SET.zip --out … --record-blobs --record-expected
    python builder/build.py --disc … --out … --record-expected          (and the option variants you ship)
    python patcher/make.py

## Checks

* `python builder/tests/check_encoders.py` — the 77 re-encoded files against the hand-made ones in `build/`
  (development machine only).
* The build prints the SHA-1 and compares it with `data/known.json`; exit status 1 on a difference.
