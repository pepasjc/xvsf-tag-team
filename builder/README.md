# builder — one command from your disc image to the patched image

    python builder/build.py --disc "path/to/original.bin" --out OUTDIR
    python builder/build.py --disc original.bin --arcade xmvsfu.zip --out OUTDIR

The first form builds the 2 MB tag hack. With `--arcade` (your own arcade ROM set; a clone zip followed by
its parent zip) the image also carries the restored animation frames for 8 MB setups. Output:
`OUTDIR/X-Men vs. Street Fighter (USA) [Tag Hack 1.3].bin` + `.cue` (`… [Tag Hack 1.3 + Restored Frames]` with an
arcade set; `--name` changes it), `build.log`, and a `.chd` with `--chd` when `chdman` is found (`XVSF_CHDMAN`,
PATH, `--chdman PATH`).

The default is the **release configuration**: boot card + version line on the main menu + the built-in achievements
([docs/xvsf/achievements.md](../docs/xvsf/achievements.md); they switch themselves off on the PS2 / PS3).

| options | 2 MB | with `--arcade` |
|---|---|---|
| (none) | boot card + version line (`--logo --title`) | boot card (`--logo`); the 8 MB loader always draws the version line |
| `--no-logo` | version line only | no boot card |
| `--no-menu-version` | boot card only | refused: the line carries the 8MB indicator |
| `--plain` | neither: the plain regression reference | no boot card: the plain 8 MB reference |
| `--buttons stock` | the game's own shoulder layout (`--nopad`) | the same (`--nopad`, handed on to the 2 MB build inside) |
| `--no-achievements` | without the built-in achievements (no `--ach`) | the same |

Requirements: Python 3.11, `numpy`, `numba`. For `--arcade`: the `zopfli` Python module (without it
`tools/mkap8disc.py` falls back to zlib and the image differs from the reference). No compiler and no fixed paths:
the builder never compiles or assembles anything (all of our MIPS code is prebaked in `data/blobs`, see below).
`python builder/build.py --help` lists the options (`--achievements` is still accepted and does nothing: achievements are
on unless `--no-achievements`; the 1.0.1 / 1.1 configurations below never have them). Two earlier releases are still built, 2 MB only and
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

Sound banks (`tools/sndpatch.py`, notes in `work/sound/IMPLEMENT.md`): every character's full bank, at quality
levels made from the user's disc at build time. `tools/snd/vab.py` edits the VAB banks, `tools/snd/resample.py`
(windowed sinc, integer table `sinc_table.py`) brings samples above a level's rate cap down to it, and
`tools/snd/adpcm.py` (search encoder: all filters and shifts, beams over nibbles and decoder states) encodes them.
Both are integer-only, so their output does not depend on the platform; their hot loops run under numba here and as
JavaScript in the browser (`patcher/src/kernels.js`: `snd_decode`, `snd_encode`, `snd_resample`). The 2 MB levels
are one pass of about 3.7 million samples through the encoder; `tools/mkap8disc.py` adds the two 8 MB levels.

The sprite encoders are ports of `tools/nsp_mid.py` and `tools/nsp_huff.py` (`xvb/xvm1.py`, `xvb/xvh1.py`)
onto batched kernels (`xvb/kernels.py`: one call per file and pass). The same kernels exist in JavaScript for
the browser patcher (`patcher/src/kernels.js`). Two things in them are there for reproducibility, not speed:

* `argsort_np` is numpy's scalar introsort, spelled out. The clustering depends on the order `np.argsort`
  gives to *equal* keys; that order differs between numpy builds (SIMD sorts), and a stable sort gives other
  files than the reference.
* `cost_argmin` replaces a dense float matrix product by exact integer sums over the non-zero entries.

## Data in this directory

* `data/tiles_mid.json`, `data/tiles_fat.json` — tile numbers per character (measurement results: which tiles
  are decoded in bursts). Copies of `work/nspm4/tiles.json` and `work/fat/tiles.json`. Their generators
  (`work/nspm4/plan.py`, `work/fat/selfat.py`) need emulator measurement logs and are not part of the build.
* `data/known.json` — SHA-1/size of the accepted input, and the SHA-1 of the output for the option
  combinations that were built here (`--record-expected`).
* `data/blobs/` — ALL of our own MIPS code, prebaked: `manifest.json` + one file per blob, named by its SHA-1
  (checked on every read; once the references below are filled in, the result is checked against the SHA-1 the
  manifest records as `resolved`). `calls`: the recorded results of the functions in `tools/` that generate code
  (`pipeline.PREBAKED`: the sprite decoders `nsppatch.patches`, the mipsasm patches `tagpatch` / `hudpatch` / `aipatch`
  / ..., the 1.1 speed modules `speedpatch.exe_patches` and stage overlays `frame.ovl_patches`, the predictor sectors
  `mktagdisc.ahead_area`, the version line `titlepatch.build`, the boot cards `logopatch.build` / `card2patch.build`,
  the 8 MB module `mkap8disc.build`, the sound code `sndpatch.code`: resident code + the sound directory's code),
  keyed by function + arguments + context (`--nospeed`, `--nosound`, the
  developers' `XV_SPEED` / `UP_*` / `XV8_*` / `XV_SNDTRACE` switches; `pipeline.call_key`); `files`: the loader `tools/tagload/tagload.*`.
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
more than the rule asks (every such pair of which at most one word is trivial). `work/release12/optA_scan.py`
checks the blobs, the patcher's bundle and the page against every file of the original disc. The tools' own
sources carry the game words they check before patching (stock code) as SHA-1 values only.

## After the tools or the arcade content builder change

On the development machine (MIPS compiler, `zopfli`, the arcade sets in `work/arcade/`):

    python work/release12/record.py --arcade-dir DIR    # bake data/blobs, check against the tools, record known.json, make the patcher
    python work/release12/record.py --check             # are the blobs current?

`record.py` empties `data/blobs` (the old copy is kept in `work/release12/blobs_prev_<time>`) and re-bakes it with
record-mode builds (`build.py --record-blobs`: the tools' own code generation runs, with the compiler; game words in
the results become references), checks those images against `tools/mktagdisc.py` / `tools/mkap8disc.py` run
directly, rebuilds every shipped configuration with no compiler reachable and records the hashes
(`--record-expected`; the 1.0.1 and 1.1 configurations must reproduce their release hashes), runs the Option A
scan, and regenerates `patcher/`. The 8 MB module does not depend on the content (the memory map
goes into the module table), so one baked `mkap8disc.build` serves every arcade set.

## Checks

* `python builder/tests/check_encoders.py` — the 77 re-encoded files against the hand-made ones in `build/`
  (development machine only).
* The build prints the SHA-1 and compares it with `data/known.json`; exit status 1 on a difference.
* `python work/release12/optA_scan.py` — no game words in `data/blobs`, the patcher bundle or `patcher/index.html`.
* `python work/release12/sndk_check.py` — the JavaScript sound kernels against the numba ones on real samples
  (development machine; needs `node`).

## Marvel Super Heroes vs. Street Fighter (builder/mshb)

The same command takes the MSHvSF disc (USA, SLUS-00793); `build.py` recognises the game from the files on the disc
(`builder/games.py`) and hands it to `builder/mshb/cli.py`:

    python builder/build.py --disc "Marvel Super Heroes vs. Street Fighter (USA).bin" --out OUTDIR
    python builder/build.py --disc original.bin --ram8 --out OUTDIR                              # with the 8 MB loader
    python builder/build.py --disc original.bin --arcade mshvsf.zip --out OUTDIR                 # 8 MB loader + restored frames
    python builder/build.py --disc original.bin --arcade mshvsfu.zip mshvsf.zip --out OUTDIR     # a clone + its parent

Output: `Marvel Super Heroes vs. Street Fighter (USA) [Tag Hack 1.0].bin` + `.cue` (`… + Restored Frames]` with an
arcade set, `… 8 MB]` with `--ram8`), `build.log`, `.chd` with `--chd`.  `--ram8`: the 8 MB loader without an
arcade set (`tools/ap8/mkap8.py` without content: all four characters full from upper RAM on 8 MB machines, the 2 MB
tag hack otherwise).  Options: `--no-logo` (no boot cards), `--meter off|on|none` (speed meter
in OPTION MODE, off at boot = the release default; on at boot; not built in), `--work DIR` (keeps the sprite tiers and
sound levels for the next run), `--jobs N`.  The default is the 1.0 release configuration (`mktag.py --meter`).
Requirements: Python 3.11, numpy, numba (the encoders run without numba too, much slower).  No compiler.

| stage | what | |
|---|---|---|
| verify | SHA-1 against `data/mshvsf/known.json` | other releases, patched images, altered dumps refused with the reason |
| extract | files of the disc into the tool root (below) | |
| sprites | 10 tiers per character (DSH1 with cut tiles, DSH1 strong, DSH1 + hot tiles, DSM1, DSM1 + hot tiles) from the stock `SP_PLxx.DSP`; the cut tier = `tools/tagload/cuttier.py` with the recorded tile list (`data/mshvsf/dsh_cut.json`) | `mshb/sprites.py`, `dsm1.py`, `dsh1.py`: ports of `common/dsp/dsm.py` / `dsh.py` onto batched kernels (`mshb/kernels.py`; JavaScript twins `patcher/src/kernels_msh.js`); the per-file (tables, classes) the development encoder found by search are in `data/mshvsf/dsh_params.json`, the play volumes of the hot tiers in `data/mshvsf/hot/` |
| sound | every level of every bank, the 23 characters + COMMON.SE (`games/mshvsf/tools/snd/sndbank.py`: resampled + ADPCM re-encoded from the disc) | parallel processes |
| arcade | `games/mshvsf/tools/ap/build8.py` from the user's arcade set (only with `--arcade`) | |
| disc | `games/mshvsf/tools/tagload/mktag.py` (2 MB) or `games/mshvsf/tools/ap8/mkap8.py --content` (8 MB), run unmodified | |
| seal | EDC/ECC of the rewritten sectors | |

How the tools run (`mshb/pipeline.py`): the files the build needs (`pipeline.ROOT_SPEC`: the tools, `common/dsp`, the
XvSF modules they import, `builder/`) are copied into `<work>/root` with the repository's layout - the browser bundle is
the same file list - and the tools run from there with their own relative paths; their data directories
(`games/mshvsf/work/loader/files`, `work/dsp/<tier>`, `work/lba_map.json`, `build/snd`, `disc/SLUS_007.93`) are filled
from the user's disc in that copy, never in the repository.  The harness gives them the user's image as `SRC_BIN`, an
Overlay for the output image, defers EDC/ECC, and replaces every function that compiles OUR code by its prebaked result
(`pipeline.PREBAKED`: the loader blobs, the 8 MB blob and menu code, the sound hook, the speed meter, the gameplay
patches, the sprite decoders, the speed modules, the boot-card stubs; plus the DSH1 decoder file), from
`data/mshvsf/blobs` (manifest + blobs named by SHA-1, game words as references to the user's disc: `xvb/gameref.py`).
Results are keyed by function + arguments + context (`menus.AP8` and the relevant tool flags).  The card 2 picture, the
relocated character overlays, the sound levels and every sprite tier are made from the user's disc at build time.

The game's tool files the build runs are a frozen copy, `data/mshvsf/tools/` (repository layout: `games/mshvsf/tools/...`,
`common/dsp/dsp.py`, `dsmpatch.py`), written by the re-bake from the sources it baked: work in `games/mshvsf/tools`
goes on without changing the release builder.  The XvSF modules they import (`tools/*.py`, `tools/snd`, `tools/ap`)
come from the repository, as for the XvSF builder.  Time on the development machine (16 cores, `--jobs 6`, empty work
directory): 2 MB 193 s, 8 MB 223 s.

Re-baking (development machine, MIPS compiler; holds `games/mshvsf/work/mktag.lock`):

    python work/mshvsf_release/record.py            # bake data/mshvsf/blobs, check record == replay (no compiler) == the rc references (known.json "reference"), record known.json

The 1.0 release images (achievements on): 2 MB `753e7b13…`, `--ram8` `50190284…`, with an arcade set (mshvsf or
mshvsfu: the same frames) `e40f9fc4…`; without achievements `fb9ca317…` / `6d976978…` / `2e8d5984…`.  Development and
release-candidate hashes are kept in known.json "previous" (refused as patched).  What the MSHvSF patch does:
[docs/mshvsf/technical.md](../docs/mshvsf/technical.md).
Checks: `python builder/tests/check_msh_sprites.py` (the encoders against `games/mshvsf/work/dsp`), the Option A scan
(`python work/release12/optA_scan.py --disc games/mshvsf/disc/mshvsf.bin --blobs builder/data/mshvsf/blobs`).
