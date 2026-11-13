# Building

Everything here runs from a checkout of this repository on Windows, Linux or macOS. You need your own
disc image, and for the restored frames your own arcade ROM set; nothing from either is in the
repository.

## Requirements

- Python 3.11 with `numpy` and `numba`; `zopfli` for the restored frames.

      pip install -r requirements.txt

  The versions in `requirements.txt` are the ones the 1.1 references were made with. Without the
  `zopfli` module the 8 MB build falls back to zlib: the image works but is not identical to the
  reference.
- `chdman` only for `--chd`.
- No MIPS compiler, unless you change the MIPS sources (see below).

## Building

    python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --out OUT
    python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --arcade xmvsfu.zip --out OUT

The first line builds the 2 MB tag hack, the second adds the restored frames for 8 MB machines. A clone
set in split form takes its parent as well: `--arcade xmvsfu1d.zip xmvsf.zip`.

| Option | Effect |
|---|---|
| `--no-logo` | no boot card |
| `--no-menu-version` | no version line on the main menu (2 MB build only; with restored frames the line carries the 8MB indicator) |
| `--plain` | neither; the plain images the regression references were made with |
| `--buttons stock` | the game's own button layout instead of HP = R1, HK = R2, 3P = L1, 3K = L2 |
| `--chd` | also write a CHD (`chdman` from PATH, `XVSF_CHDMAN` or `--chdman`) |
| `--work DIR` | keep the work directory; the re-encoded sprites are reused on the next run |
| `--jobs N` | processes for the sprite encoders |

The input image is checked by SHA-1 first; anything but the known dump is refused with the reason
(already patched, other region, not this game, altered). Every intermediate file is regenerated from the
inputs, and the result is compared with the reference SHA-1 for the chosen options
(`builder/data/known.json`). A build takes one to three minutes; the restored frames add about two.
Details of each stage: [builder/README.md](builder/README.md).

## The web patcher

`patcher/index.html` is generated from the same tools:

    python patcher/make.py

It bundles `builder/` and `tools/` into the page; the page runs them under Pyodide in a Web Worker and
gives the same image as the command line. [patcher/README.md](patcher/README.md) covers hosting and the
browser tests.

## Changing the MIPS code

The code that runs on the PlayStation is stored assembled in `builder/data/blobs/`: one file per piece,
named by its SHA-1, and `manifest.json`, which maps every code-generating function in `tools/` and its
arguments to its piece. A normal build only reads these, so neither the builder nor the web patcher needs a
compiler. The sources:

| Source | What it is |
|---|---|
| `tools/tagload/` | the battle loader (C and assembly; its linked output is also kept in `tools/tagload/*.bin`) |
| `tools/nspdec/nspdec.S` | the 1.0.x sprite decoders (`--nospeed`) |
| `tools/speed/decode/` | the 1.1 tile decoders and the decode-ahead predictor |
| `tools/speed/upload/`, `quad/`, `frame/`, `logic/` | the 1.1 sprite upload, quad builder, main loop and GPU queue, game logic; `frame/bgtile.py` and `bghand.py` generate the stage background rewrites |
| `tools/ap8/` | the 8 MB boot stub and module |
| `tools/logo/` | the boot cards (`logo.S`, `card2.S`; `card.bin` and `card2.bin` are the cards' own artwork) |
| `tools/*patch.py` | patches assembled by `tools/mipsasm.py` (tag, HUD, CPU, rounds, music, ...) and the version line |

After changing a source you need a `mipsel-none-elf-` GCC toolchain (binutils and gcc), plus `capstone`
for the load-delay check of the speed modules. It is found through `XVSF_MIPS_PREFIX`, else
`mipsel-none-elf-gcc` on PATH, else `local_paths.json` in the repository root (copy
`local_paths.example.json`). Then:

1. Rebuild what you changed. The battle loader:
   `python -c "import sys; sys.path.insert(0, 'tools'); import mktagdisc; mktagdisc.build()"`.
   The speed modules: `python tools/speed/decode.py build`, `python tools/speed/quad.py build`,
   `python tools/speed/logic.py build`, `python tools/speed/frame.py build` (in this order: `frame` reads
   `decode`'s symbols; the upload module is compiled on the fly). `frame.py build` reads the original stage
   files from `disc/files/P/P4/` in the repository root (extract them from your disc image).
2. Re-bake the blobs with record-mode builds, which run the tools' own code generation instead of reading
   the blobs and store the results:

       python builder/build.py --disc … --out OUT --record-blobs
       python builder/build.py --disc … --out OUT --record-blobs --tool-flag=--nospeed
       python builder/build.py --disc … --arcade xmvsfu.zip xmvsf.zip --out OUT --record-blobs

   These three cover every piece; the other options only leave pieces out. Old pieces that are no longer
   referenced can be deleted from `builder/data/blobs/` together with their manifest entries.
3. Build every configuration you ship again with no compiler reachable, and store the new reference
   hashes: `python builder/build.py … --record-expected` (once per option combination).
4. `python patcher/make.py`.

The maintainers run steps 2 to 4 with one script that also checks the record-mode images against the
tools run directly; that script is not part of this repository. When a `tools/` file differs from the
one the blobs were baked from, the build prints a note; the image is still built from the blobs.

A change to anything the image contains changes the reference hashes; `--record-expected` writes the
new ones for the options of that run.
