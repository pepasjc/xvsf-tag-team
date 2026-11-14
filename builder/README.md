# builder — one command from your disc image to the patched image

    python builder/build.py --disc "path/to/original.bin" --out OUTDIR
    python builder/build.py --disc original.bin --arcade xmvsfu.zip --out OUTDIR

The first form builds the 2 MB tag hack. With `--arcade` (your own arcade ROM set; a clone zip followed by
its parent zip) the image also carries the restored animation frames for 8 MB setups. Output:
`OUTDIR/X-Men vs. Street Fighter (USA) [Tag Hack 1.2].bin` + `.cue` (`… [Tag Hack 1.2 + Restored Frames]` with an
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
`tools/mkap8disc.py` falls back to zlib and the image differs from the reference). No compiler and no fixed paths:
the builder never compiles or assembles anything (all of our MIPS code is prebaked in `data/blobs`, see below).
`python builder/build.py --help` lists the options. Two earlier releases are still built, 2 MB only and
bit-identical to the released images (their hashes are in `data/known.json`): `--tool-flag=--nospeed` gives 1.0.1
(no 1.1 speed-ups, no 1.2 sound), `--tool-flag=--nosound` gives 1.1 (no 1.2 sound banks; version line
"TAG HACK 1.1").

## What it does

| stage | input | output (work directory) |
|---|---|---|
| verify | the image | SHA-1 and size against `data/known.json`; anything else is refused, with the reason (already patched, other region, not this game, not a raw image, altered dump) |
| extract | the image | `files/…` (every file up to 8 MB), `lba_map.json` |
| sprites | `files/A/A0/SP_PLxx.NSP`, `A2/SP_EFF1.NSP`, `data/tiles_*.json`, `data/hot_tiles.json` | `build/nspm` (base, XVM1), `build/nsp` (strong, XVH1; 1.0.x), `build/nsph4` (1.1 strong: XVH1 + its most decoded tiles as stock RLE, `xvb/strongrle.py`), `build/nspm4` (mid), `build/nspfat2` (fat), `build/nspm_eff` |
| arcade (only with `--arcade`) | the ROM zip(s), the image | `ap8content_base/` — `tools/ap/build8.py --direct --shared`; then `ap8content/` — `tools/ap/sel2build.py --base ap8content_base` (second select-screen sprite set); `ap8content_eff/` — `tools/ap/eff2build.py` (common effects file); `ap8content_snd8/` — `tools/ap/snd8build.py` (the arcade samples the PS1 has no sound for: Wolverine's third tag voice) |
| disc | all of the above, `data/blobs` | the patched image: `tools/mktagdisc.py`, or `tools/mkap8disc.py` (which runs the former inside). On the way the sound banks of every quality level are rebuilt from the image's own sound files (`tools/sndpatch.py`, below; cached in `build/snd/`) |
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

Sound banks (`tools/sndpatch.py`): every character's full bank, at quality levels made from the user's disc at
build time. `tools/snd/vab.py` edits the VAB banks, `tools/snd/resample.py` (windowed sinc, integer table
`sinc_table.py`) brings samples above a level's rate cap down to it, and `tools/snd/adpcm.py` (search encoder: all
filters and shifts, beams over nibbles and decoder states) encodes them. Both are integer-only, so their output does
not depend on the platform; their hot loops run under numba here and as JavaScript in the browser
(`patcher/src/kernels.js`: `snd_decode`, `snd_encode`, `snd_resample`). The 2 MB levels are one pass of about
3.7 million samples through the encoder; `tools/mkap8disc.py` adds the two 8 MB levels.

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
* `data/hot_tiles.json` — per character, the decoded bytes of each tile in play (measured on the original disc). The 1.1
  strong tier (`xvb/strongrle.py`) keeps the most decoded tiles of each XVH1 file as stock RLE, up to 4 KB per
  character. Measurement data, like the two lists above.
* `data/known.json` — SHA-1/size of the accepted input, and the SHA-1 of the output for the option
  combinations that were built here (`--record-expected`).
* `data/blobs/` — ALL of our own MIPS code, prebaked: `manifest.json` + one file per blob, named by its SHA-1
  (checked on every read; once the references below are filled in, the result is checked against the SHA-1 the
  manifest records as `resolved`). `calls`: the recorded results of the functions in `tools/` that generate code
  (`pipeline.PREBAKED`: the sprite decoders `nsppatch.patches`, the mipsasm patches `tagpatch` / `hudpatch` / `aipatch`
  / ..., the 1.1 speed modules `speedpatch.exe_patches` and stage overlays `frame.ovl_patches`, the predictor sectors
  `mktagdisc.ahead_area`, the version line `titlepatch.build`, the boot cards `logopatch.build` / `card2patch.build`,
  the 8 MB module `mkap8disc.build`, the sound code `sndpatch.code`: resident code + the sound directory's code),
  keyed by function + arguments + context (`--nospeed`, `--nosound`, the developers' `XV_SPEED` / `UP_*` / `XV8_*` /
  `XV_SNDTRACE` switches; `pipeline.call_key`); `files`: the linked loader (`tools/tagload/`, built from
  `tagload.c` + `glue.S`).
  The builder installs these in place of the functions and runs no external program at all (a tool that tries to is
  stopped with an error). `sources` records the SHA-1 of every `tools/` file at bake time: `build.py` notes when the
  tools changed since (`pipeline.stale_sources()`). The second card's blob is only its stub: its picture is composed
  at build time from the user's disc (`tools/card2patch.py`).

No graphics, sound, code or other data from the game or the arcade ROMs is here. Where a rewritten routine keeps
some of the original instructions unchanged (or moves them), the blob does not contain those words: it stores a
reference ("N bytes of file F at offset O", `xvb/gameref.py`), and the builder fills it in from the files of the
user's own image after the SHA-1 check. In a blob a bytes value is `{"__bytes__": hex}` (nothing of the game in it)
or `{"__bref__": [hex | [file, offset, count], ...]}`. The rule: no stored byte string contains two consecutive
32-bit words (at any byte offset) equal to two words at a 4-byte-aligned offset of any file of the original disc,
unless at least one of the two is trivial (0, 0xffffffff, `jr ra` 0x03e00008, or 1..0xff). The encoder references
more than the rule asks (every such pair of which at most one word is trivial). The tools' own sources carry the
game words they check before patching (stock code) as SHA-1 values only.

## After the tools or the arcade content builder change

The blobs are made by the tools' own code generation, which needs a `mipsel-none-elf-` GCC toolchain (found through
`XVSF_MIPS_PREFIX`, `--mips-prefix`, PATH or `local_paths.json`, see `tools/toolenv.py`). A record-mode build runs it
instead of reading the blobs and stores what it produced (game words in the results become references to the disc):

    python builder/build.py --disc … --out … --record-blobs                              # 2 MB 1.2 (boot card, version line)
    python builder/build.py --disc … --out … --record-blobs --tool-flag=--nospeed        # 2 MB 1.0.1
    python builder/build.py --disc … --out … --record-blobs --tool-flag=--nosound        # 2 MB 1.1
    python builder/build.py --disc … --arcade SET.zip … --out … --record-blobs           # 8 MB

These four cover every prebaked function and context; the other option combinations only leave pieces out. The
speed modules read their own assembled code from `tools/speed/<module>/` (and `tools/speed/frame/bin/`): build those
first with `python tools/speed/decode.py build`, `quad.py build`, `logic.py build` and `frame.py build` (the stage
background rewrite reads the original stage files from `disc/files/P/P4/` in the repository root). Then rebuild every
configuration you ship with no compiler reachable, compare, and record the reference hashes with `--record-expected`
(the 1.0.1 and 1.1 configurations must reproduce their release hashes); finally `python patcher/make.py`. The 8 MB module does not depend on the content (the memory map goes into the module table), so one baked
`mkap8disc.build` serves every arcade set.

## Checks

* `python builder/tests/check_encoders.py` — the 77 re-encoded files against the hand-made ones in `build/`
  (development machine only).
* The build prints the SHA-1 and compares it with `data/known.json`; exit status 1 on a difference.
