# Building

Everything here runs from a checkout of this repository on Windows, Linux or macOS. You need your own
disc image, and for the restored frames your own arcade ROM set; nothing from either is in the
repository.

## Requirements

- Python 3.11 with `numpy` and `numba`; `zopfli` for the restored frames.

      pip install -r requirements.txt

  The versions in `requirements.txt` are the ones the 1.0 references were made with. Without the
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

The code that runs on the PlayStation is stored compiled:

| Source | Compiled form |
|---|---|
| `tools/tagload/` (battle loader) | `tools/tagload/*.bin`, `tagload.sym` |
| `tools/nspdec/nspdec.S` (sprite decoder) | `tools/nspdec/nspdec.bin`, `nspdec.sym` |
| `tools/ap8/` (8 MB stub and module), `tools/logo/` (boot card), the version line | `builder/data/toolcache/*.json`, keyed by a hash of the sources and the arguments |

After changing a source you need a `mipsel-none-elf-` GCC toolchain. It is found through
`XVSF_MIPS_PREFIX`, else `mipsel-none-elf-gcc` on PATH, else `local_paths.json` in the repository root
(copy `local_paths.example.json`). Then:

    python -c "import sys; sys.path.insert(0, 'tools'); import mktagdisc; mktagdisc.build()"   # the battle loader
    python tools/nsppatch.py build                                                              # the sprite decoder
    python builder/build.py ... --record-blobs                 # recompile and store the module, boot card, version line
    python builder/build.py ... --record-expected              # store the new reference SHA-1 for those options

A change to anything the image contains changes the reference hashes; `--record-expected` writes the
new ones for the options of that run.
