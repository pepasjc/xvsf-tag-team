# builder — one command from your disc image to the patched image

    python builder/build.py --disc "path/to/original.bin" --out OUTDIR
    python builder/build.py --disc original.bin --arcade xmvsfu.zip xmvsf.zip --out OUTDIR

`build.py` recognises the game from the files on the disc (`builder/games.py`) and hands it to its package:
X-Men vs. Street Fighter `xvb` (this page), Marvel Super Heroes vs. Street Fighter `mshb`, Marvel vs. Capcom `mvcb`
(sections below). The first form builds the 2 MB tag hack. With `--arcade` (your own arcade ROM set; a clone zip
followed by its parent zip) the image also carries the 8 MB parts. Output for X-Men vs. Street Fighter:
`OUTDIR/X-Men vs. Street Fighter (USA) [Tag Hack 1.4].bin` + `.cue` (`… [Tag Hack 1.4 + Restored Frames]` with an
arcade set; `--name` changes it), `build.log`, and a `.chd` with `--chd` when `chdman` is found (`XVSF_CHDMAN`,
PATH, `--chdman PATH`).

The default is the **release configuration**: boot card + version line on the main menu + the built-in achievements
(docs/xvsf/achievements.md; they switch themselves off on the PS2 / PS3).

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

Output: `Marvel Super Heroes vs. Street Fighter (USA) [Tag Hack 1.1].bin` + `.cue` (`… + Restored Frames]` with an
arcade set, `… 8 MB]` with `--ram8`), `build.log`, `.chd` with `--chd`.  `--ram8`: the 8 MB loader without an
arcade set (`tools/ap8/mkap8.py` without content: all four characters full from upper RAM on 8 MB machines, the 2 MB
tag hack otherwise).  Options: `--no-logo` (no boot cards), `--no-achievements`, `--work DIR` (keeps the sprite
tiers and sound levels for the next run), `--jobs N`.  The default is the 1.1 release configuration
(`pipeline.RELEASE_11`: `mktag.py --meter --ach --mcfix --exopt --stageanim --l2g --cyswap --arcbal --vsmenu --nori
--infmeter --nosmrow --achpop --title=TAG HACK 1.1` = games/mshvsf/build/m11_f8; 8 MB `pipeline.RELEASE8`: the same without
`--l2g`, plus `--sn8full` and, with an arcade set, the arcade voices `--sn8arc` = build/mshvsf_ap8_f11).  `--meter on` /
`none` are refused (1.1 has no speed meter row; its option bytes live in the meter's flag word).
Requirements: Python 3.11, numpy, numba (the encoders run without numba too, much slower), scipy (8 MB arcade voices:
tools/snd/sn8build.py).  No compiler.

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

    python work/release14/record_msh.py             # 1.1: bake data/mshvsf/blobs, record == replay (no compiler) == the finals (known.json "reference"), known.json

The 1.1 configurations reproduce games/mshvsf/build/m11_gf1.bin (sha1 `0c782cd7…`) and, with mshvsf or mshvsfu,
mshvsf_ap8_i23e.bin (`586bf8b5…`, 8 MB with the GitHub #23 fix `--work2`); `--ram8` `e944cd90…` (11 configurations, re-baked 2026-11-27).  Every 8 MB
image is a DUAL image (builder/mshb/dual.py): the 2 MB build with the same options + the 8 MB build appended, switched over
only by a boot-time 8 MB test, so on a 2 MB console it runs exactly the 2 MB disc.
The 1.0 release configurations reproduced `games/mshvsf/build/mshvsf_rc1.bin` (`mktag.py --meter`: `fed1e957…`) and
`mshvsf_ap8_rc1.bin` (`mkap8.py --meter`, no content = `--ram8`: `48682176…`); with an arcade set (mshvsf or
mshvsfu: the same frames) `85931314…`.  The v10 hashes are kept in known.json "previous" (refused as patched).
Checks: `python builder/tests/check_msh_sprites.py` (the encoders against `games/mshvsf/work/dsp`), the Option A scan
(`python work/release12/optA_scan.py --disc games/mshvsf/disc/mshvsf.bin --blobs builder/data/mshvsf/blobs`).

## Marvel vs. Capcom (builder/mvcb)

The same command takes the MvC disc (USA, SLUS-01059); `build.py` recognises it (`builder/games.py`) and hands it to
`builder/mvcb/cli.py`:

    python builder/build.py --disc "Marvel vs. Capcom - Clash of Super Heroes (USA).bin" --out OUTDIR             # 2 MB
    python builder/build.py --disc original.bin --arcade mvsc.zip --out OUTDIR                                   # 8 MB + arcade voices

Output `Marvel vs. Capcom (USA) [Tag Hack 1.0].bin` + `.cue` (`… [Tag Hack 1.0 8MB]` with an arcade set), `build.log`,
`.chd` with `--chd`.  No other options: the images are the finals (data/mvc/configs.json: the tools' own argument list and
environment of each final, recorded by the bake).  Requirements: Python 3.11, numpy, numba (much slower without),
scipy (8 MB arcade voices).  No compiler.

| stage | what | |
|---|---|---|
| verify | SHA-1 against `data/mvc/known.json` | other releases, patched images, altered dumps refused with the reason |
| root | the frozen tool files (`data/mvc/tools`, repository layout; list `data/mvc/rootfiles.json`) -> `<work>/root` | |
| extract | every file of the disc -> `<root>/games/mvc/work/disc_files`, lba map | |
| derive | every non-stock file the tools read, rebuilt from the user's disc (`data/mvc/derived.json`, in order) | `mvcb/fxhalf.py`, `pairs.py`, `tiers.py`, `codecs.py` |
| sound | every level of every sound bank (`games/mvc/tools/snd/sndbank.py`, parallel processes) | the cache mktag.py reads |
| disc | `games/mvc/tools/tagload/mktag.py` (2 MB) or `games/mvc/tools/ap8/mkap8.py --arcade ZIP` (8 MB), run unmodified in the root | |
| seal | EDC/ECC of the rewritten sectors | |

What `derived.json` holds per file (kinds): `disc` (a stock file of the disc, by name), `fx` (the half-resolution
effects A0 of a character: the stock A0 with the listed tiles point-sampled, `mvcb/fxhalf.py` = tools/fxhalf build),
`pair` (store-once pair union A0 + its json: tools/speed5/pairs.py build, `mvcb/pairs.py`), `tier` (a sprite tier file:
DSH1 / DSM1 / DSR1 / RLE, see below), `diff` (copy runs from other derived / stock files at any offset + our literal
bytes: the assists' .pix / .tab / variants), `data` (our own data file, `data/mvc/files/<sha1>`: plans, tables,
decoders).  Every entry carries the SHA-1 it must come out with.

Sprite tiers (`mvcb/tiers.py`): the recipe of a tier file is OUR part only - the codec model read back from the file
(code tables, context maps, probabilities: the encoder's choices), the frame-group rewrites of our cut tiers as
"group g shows the parts of group k" (+ coordinate modes), the tile table bytes we changed, the padding - and for each
coded tile where its content comes from: the same tile of the base DSP (the stock file, the half-res effects A0, the
pair union), zeros (tiles our cuts freed), or another base tile.  The builder re-emits every tile stream with the
encoder's own emission step (`mvcb/codecs.py`: dsh.encode / dsm.encode / codec2/dsr.py with the model given, parse
and entropy coding unchanged), so the file comes out byte for byte; no model search runs (the 2 MB tree took about
2 hours of encoder search to make).

Our MIPS code (`mvcb/toolbake.py`): the toolchain is prebaked per COMMAND.  Record runs every gcc / as / ld / objcopy /
nm / objdump command for real and keys it by the tool + its arguments with every input file replaced by the SHA-1 of
its content (text normalised: machine paths, and runs of `.set` / `#define` lines sorted - generated sources list
them in hash-randomised set order) plus the content of every file a source #includes; outputs the Python tools read
(.bin, nm / objdump text, ld's stderr) are stored (`data/mvc/tc`, game words as references, xvb/gameref.py), the
others (.o, .elf) as tokens.  The builder replaces `subprocess.run / check_call / check_output / call` while the tools
run; a command with no record is an error.  The harness also redirects `games/mvc/disc/mvc.bin` to the user's image,
makes the output image an Overlay and defers EDC/ECC (`mkdisc.fix_sector`).

Re-baking for a new final (development machine, MIPS compiler, the user's arcade set; holds games/mvc/work/mktag.lock;
about an hour, run it detached through tools/heavyslot.py):

    python work/mvcb/record_mvc.py --flags games/mvc/work/stfx/rc3/flags_mvc_1_0c.txt --ref2 mvc_1_0c --ref8 mvc_8_1_2

1. trace: a real build of each configuration in the repository under an audit hook (`work/mvcb/trace.py`: every file
   opened, every toolchain command, every module); the image must equal the final;
2. classify: every input -> derived.json / rootfiles.json / data/mvc/files (each recipe is checked to rebuild the file);
3. record: a build in a FRESH tool root filled only from those recipes, with the compiler (toolchain recorded); then
   the tool files are frozen into data/mvc/tools;
4. replay: the builder's own path in another fresh root with no compiler reachable; both images must equal the final;
   known.json gets the hashes.
Check: `python work/release12/optA_scan.py --disc games/mvc/disc/mvc.bin --blobs "" --bundle "" --page "" --tree builder/data/mvc`.
