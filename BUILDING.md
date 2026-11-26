# Building

Everything here runs from a checkout of this repository on Windows, Linux or macOS. You need your own disc image,
and for the restored frames your own arcade ROM set; nothing from either is in the repository. One builder makes
both hacks: it recognises the game from the files on the disc.

## Requirements

- Python 3.11 with `numpy` and `numba`; `zopfli` for the restored frames.

      pip install -r requirements.txt

  The versions in `requirements.txt` are the ones the reference images were made with. Without the `zopfli`
  module the restored-frames build of X-Men vs. Street Fighter falls back to zlib: the image works but is not
  identical to the reference.
- `chdman` only for `--chd`.
- No MIPS compiler, unless you change the MIPS sources (see below).

## Building

    python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --out OUT
    python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --arcade xmvsfu.zip xmvsf.zip --out OUT
    python builder/build.py --disc "Marvel Super Heroes vs. Street Fighter (USA).bin" --out OUT
    python builder/build.py --disc "Marvel Super Heroes vs. Street Fighter (USA).bin" --arcade mshvsf.zip --out OUT
    python builder/build.py --disc "Marvel vs. Capcom - Clash of Super Heroes (USA).bin" --out OUT
    python builder/build.py --disc "Marvel vs. Capcom - Clash of Super Heroes (USA).bin" --arcade mvsc.zip --out OUT

Without options the builder makes the release image, the same one the web patcher makes. `--arcade` adds the
restored frames for 8 MB machines; a clone set in split form takes its parent as well (`--arcade xmvsfu1d.zip
xmvsf.zip`, `--arcade mshvsfu.zip mshvsf.zip`).

The input image is checked by SHA-1 first; anything but the known dump is refused with the reason (already patched,
other region, not this game, altered). Every intermediate file is regenerated from the inputs, and the result is
compared with the reference SHA-1 for the chosen options (`builder/data/known.json`,
`builder/data/mshvsf/known.json`, `builder/data/mvc/known.json`). A build takes a few minutes; the restored frames add a few more. Details of
each stage: [builder/README.md](builder/README.md).

### Options for both games

| Option | Effect |
|---|---|
| `--no-achievements` | leave out the built-in achievements (ACHIEVEMENTS page, popups, memory card file) |
| `--no-logo` | no boot cards |
| `--chd` | also write a CHD (`chdman` from PATH, `XVSF_CHDMAN` or `--chdman`) |
| `--name NAME` | base name of the output files |
| `--work DIR` | keep the work directory; the re-encoded sprites (and sound levels) are reused on the next run |
| `--jobs N` | processes for the encoders |
| `--verbose` | print the tools' own output |

### X-Men vs. Street Fighter only

| Option | Effect |
|---|---|
| `--no-menu-version` | no version line on the main menu (2 MB build only; with restored frames the line carries the 8MB indicator) |
| `--plain` | no boot card and no version line; the plain images the regression references were made with |
| `--buttons stock` | the game's own button layout instead of HP = R1, HK = R2, 3P = L1, 3K = L2 |
| `--tool-flag=--nosound` | the 1.1 image (2 MB only, without the 1.2 sound banks and everything newer) |

The 1.3 images are no longer built (they are recognised as already patched).
| `--tool-flag=--nospeed` | the 1.0.1 image (2 MB only, without the 1.1 speed-ups and everything newer) |

`--nospeed` and `--nosound` rebuild the earlier releases bit for bit, so their results match the hashes published
with 1.0.1 and 1.1.

### Marvel Super Heroes vs. Street Fighter only

| Option | Effect |
|---|---|
| `--ram8` | the 8 MB loader without an arcade set (all four characters in the stock sprite format from upper RAM on 8 MB machines; the image still runs on 2 MB). An arcade set implies it |
| `--meter on` | the SPEED METER on at boot (default: in EX OPTIONS, off) |
| `--meter none` | no SPEED METER code: 8 MB loader images only (the 1.1 EX OPTIONS menu carries the meter) |

The 8 MB loader images (`--ram8`, or with an arcade set) are built as 1.0.1: the 1.0 features plus the
final-boss freeze fix and the Blackheart fix; EX OPTIONS, ARCADE BALANCE and VERSUS CPU are in the 2 MB image.

### Marvel vs. Capcom

The builder makes the two release images only (2 MB; 8 MB with `--arcade mvsc.zip`); the options above for both
other games do not apply, except `--out`, `--name`, `--work`, `--jobs` and `--chd`. The MvC build runs the hack's own tools unmodified
from the frozen copy in `builder/data/mvc/tools` (sources under `games/mvc/tools/`, shared parts in `tools/` and
`common/`), with the MIPS toolchain's results recorded in `builder/data/mvc/tc`; see
[builder/README.md](builder/README.md).

## The web patcher

`patcher/index.html` is generated from the same tools:

    python patcher/make.py

It bundles `builder/` and the tools the builds run into one page; the page runs them under Pyodide in a Web Worker
and gives the same image as the command line with no options (with `--arcade` when an arcade ROM set is given).
The page has no options and is available in English and Brazilian Portuguese.
[patcher/README.md](patcher/README.md) covers hosting and the browser tests.

## Changing the MIPS code (X-Men vs. Street Fighter)

The code that runs on the PlayStation is stored assembled in `builder/data/blobs/`: one file per piece,
named by its SHA-1, and `manifest.json`, which maps every code-generating function in `tools/` and its
arguments to its piece. A normal build only reads these, so neither the builder nor the web patcher needs a
compiler. Where our code keeps some of the game's own instructions, a blob holds a reference to your disc
instead of the words, and the builder fills them in from your image. The sources:

| Source | What it is |
|---|---|
| `tools/tagload/` | the battle loader (C and assembly) |
| `tools/nspdec/nspdec.S` | the 1.0.x sprite decoders (`--nospeed`) |
| `tools/speed/decode/` | the 1.1 tile decoders and the decode-ahead predictor |
| `tools/speed/upload/`, `quad/`, `frame/`, `logic/` | the 1.1 sprite upload, quad builder, main loop and GPU queue, game logic; `frame/bgtile.py` and `bghand.py` generate the stage background rewrites |
| `tools/snd/sndres.S`, `snddir.c`, `snd.h` | the 1.2 sound code: resident part and the sound directory (`tools/sndpatch.py` assembles them; `tools/snd/*.py` rebuild the sound banks from your disc at build time) |
| `tools/ap8/` | the 8 MB boot stub and module |
| `tools/logo/` | the boot cards (`logo.S`, `card2.S`; `card.bin` and `card2.bin` are the cards' own artwork) |
| `tools/*patch.py` | patches assembled by `tools/mipsasm.py` (tag, HUD, CPU, rounds, music, START skip, ARCADE BALANCE, ...) and the version line |
| `tools/ach/` | the 1.3 achievements runtime (`ach.c`, `eval.c`, `copy.S`, `start.S`; shared with MSHvSF) and the XvSF port and set (`xvsf/`); `xvach.py` patches it in |
| `tools/skip/xvskip.c` | the 1.3 START skip |
| `tools/exopt/xvex.c`, `tools/expatch.py` | the 1.4 EX OPTIONS menu, pause rows, FRAME SKIP, STAGE ANIM, SPEED METER |
| `tools/mtap/` + `common/mtap/` | the 1.4 VERSUS CPU main-menu row (`mtmenu.h`, `mtgame.h`, `xvmtap.py`; the shared core `mtcore.c`, `mtvsui.c`, `mtbuild.py`, `mtpatch.py`) |
| `tools/tagload/r12/` | the 1.2 battle loader, kept for the `--nospeed` / `--nosound` images |

After changing a source you need a `mipsel-none-elf-` GCC toolchain (binutils and gcc), plus `capstone`
for the load-delay check of the speed modules. It is found through `XVSF_MIPS_PREFIX`, else
`mipsel-none-elf-gcc` on PATH, else `local_paths.json` in the repository root (copy
`local_paths.example.json`). Then:

1. Build the linked code the record-mode builds read (not kept in the repository). The battle loader:
   `python -c "import sys; sys.path.insert(0, 'tools'); import mktagdisc; mktagdisc.build()"`; the 1.0.x
   sprite decoders:
   `python -c "import sys; sys.path.insert(0, 'tools'); import nsppatch; nsppatch.build()"`.
   The speed modules: `python tools/speed/decode.py build`, `python tools/speed/quad.py build`,
   `python tools/speed/logic.py build`, `python tools/speed/frame.py build` (in this order: `frame` reads
   `decode`'s symbols; the upload module is compiled on the fly). `frame.py build` reads the original stage
   files from `disc/files/P/P4/` in the repository root (extract them from your disc image).
2. Re-bake the blobs with record-mode builds, which run the tools' own code generation instead of reading
   the blobs and store the results:

       python builder/build.py --disc … --out OUT --record-blobs
       python builder/build.py --disc … --out OUT --record-blobs --tool-flag=--nospeed
       python builder/build.py --disc … --out OUT --record-blobs --tool-flag=--nosound
       python builder/build.py --disc … --arcade xmvsfu.zip xmvsf.zip --out OUT --record-blobs

   These four cover every piece of the default images. The achievements code depends on the boot chain, so
   `--no-logo`, `--no-menu-version`, `--plain` and `--no-achievements` need their own record-mode run
   (the 1.4 release baked each of them, 2 MB and 8 MB). Old pieces that are no longer
   referenced can be deleted from `builder/data/blobs/` together with their manifest entries.
3. Build every configuration you ship again with no compiler reachable, and store the new reference
   hashes: `python builder/build.py … --record-expected` (once per option combination). The
   `--nospeed` and `--nosound` builds must still give the 1.0.1 and 1.1 hashes.
4. `python patcher/make.py`.

When a `tools/` file differs from the one the blobs were baked from, the build prints a note; the image
is still built from the blobs.

A change to anything the image contains changes the reference hashes; `--record-expected` writes the
new ones for the options of that run.

## Changing the MIPS code (Marvel Super Heroes vs. Street Fighter)

The same scheme: our MIPS code is stored compiled in `builder/data/mshvsf/blobs/` (game words as references
filled in from your disc), and the build never compiles anything. The Python tools the build runs are a frozen
copy in `builder/data/mshvsf/tools/` (repository layout), so the blobs always match the tools that use them.
The sources of our MSHvSF code:

| Source | What it is |
|---|---|
| `games/mshvsf/tools/tagload/` | the battle loader (`tagload.c`, `glue.S`), `mktag.py` builds the 2 MB image |
| `games/mshvsf/tools/ap8/` | the 8 MB loader and its menu code; `mkap8.py` builds the 8 MB image |
| `games/mshvsf/tools/gameplay/` | the tag-mode switch, menus, version line, secret characters, training; 1.1: EX OPTIONS (`exopt.py`, `opts.S`, `exopt.S`), ARCADE BALANCE (`arcbal.py`), the final-boss fix (`cyswap.py`, `cyswap.S`) |
| `games/mshvsf/tools/l2/` | 1.1: sprite data packed by frame group and its reader |
| `games/mshvsf/tools/mtap/` + `common/mtap/` | 1.1: the VERSUS CPU main-menu row (shared core with X-Men vs. Street Fighter) |
| `games/mshvsf/tools/speed/` | memory routines, parsers, decode-ahead, speed meter |
| `games/mshvsf/tools/snd/` | the sound bank loader and the bank builder |
| `games/mshvsf/tools/skip/`, `ach/` | START skip; the achievements port layer and set (the runtime is `tools/ach/`) |
| `common/dsp/` | the DSM1 / DSH1 sprite codecs (`dsm.py`, `dsh.py`) and their decoders (`dsmdec.S`, `dshdec.S`) |

Re-baking the MSHvSF blobs after a change needs the MIPS toolchain and the development scripts that freeze the
tool copy and record the blobs and hashes; those scripts are not part of this repository yet.

