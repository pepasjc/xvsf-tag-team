# X-Men vs. Street Fighter: Tag Team Hack (PlayStation)

**Version 1.0.1**, 2026, by pepa

Capcom treated us PlayStation fans really poorly, releasing crippled versions of all their CPS2
fighting games. The Saturn got a really good port, and even the N64 got a nice fan port, so I thought
the PlayStation deserved better.

This patch restores the full 2-on-2 tag team to the PlayStation port, on a stock console. It also adds
new 8 MB support, restoring the arcade animation frames the port cut, for those with a modded
PlayStation, a MiSTer FPGA or a compatible emulator. To enable it, give the patcher your
*X-Men vs. Street Fighter* CPS2 ROM set (`xmvsf`, `xmvsfu` or `xmvsfu1d`) along with your disc.

In the original PlayStation port the partner is a cut-down character that can only jump in for an
assist or a team super: the tag button does nothing, and a knocked-out character ends the round. The
arcade's tag system is still in the game, switched off; the hard part was fitting four full characters
into the PlayStation's 2 MB of RAM.

**Contents:** [What it does](#what-it-does) · [Restored frames](#restored-frames-8-mb) ·
[How to apply](#how-to-apply) · [Compatibility](#compatibility) · [Known issues](#known-issues) ·
[How it works](#how-it-works) · [Documentation](#documentation) ·
[Building from source](#building-from-source) · [Changelog](#changelog) ·
[Reporting bugs](#reporting-bugs) · [License](#license-and-reuse) · [Credits](#credits)

## What it does

- All four characters of a match are loaded in full, with no disc access during a fight.
- **Tag** at any time with **HP + HK**. The partner jumps in with an attack and becomes the playable
  character, with its whole move set. After a tag there is a short lockout, as in the arcade.
- Each character has its own life bar, both shown per side, the benched one small, as in the arcade.
- Only the character on the bench recovers its red (recoverable) life. A character that comes in loses
  the red part it has not recovered.
- A knocked-out character is replaced by its partner. The match is a single round and ends when both
  characters of a team are down.
- The CPU tags on its own, with the game's own arcade logic.
- You can tag against the final boss, Apocalypse.
- Team super and counter assist need a partner that is still standing.
- After a knock-out the music switches to the incoming character's theme.
- The CPU's difficulty ramps up during the first fight as in the arcade (the port started at the cap),
  and the round timer runs at the arcade's speed.
- Default buttons: HP = R1, HK = R2, three punches = L1, three kicks = L2, so tag is R1 + R2. KEY CONFIG
  in the options still changes them; the patcher can also keep the game's own layout.
- Battle loading is faster than on the retail disc.
- A short boot card before the game, and the version on the main menu.

## Restored frames (8 MB)

The PlayStation port dropped many of the arcade game's animation frames. Built together with your own
arcade ROM set, the image also carries those frames, converted from the arcade graphics while the patch
is built on your computer.

- **Restored:** Wolverine, Cyclops, Storm, Rogue, Gambit, Sabretooth, Juggernaut, Magneto, Dhalsim,
  Zangief and Cammy, three cut sprites of Ryu, the character select screen (both portrait sets), and
  some common effects (the regeneration sparkle, throw debris, Storm's bubbles, Cyclops' rings).
- **Not restored:** Ken, Chun-Li, M. Bison, Akuma, Charlie and Apocalypse keep the port's frames.
  Gambit and Magneto are partly restored (a limit of the sprite format). Animations whose restored
  frames would slow the game down were measured one by one and keep the port's frames.
- The frames are used only on a machine with **8 MB of RAM**. The main menu then shows "8MB" after the
  version, and OPTION MODE gets one more line, **ARCADE FRAMES ON / OFF**: OFF plays with the port's
  frames for the session (it is ON at every start). On a stock 2 MB console the same image plays as the
  normal tag hack.
- **Shorter loading with 8 MB:** characters stay in memory between fights, and the files the select,
  win and VS screens read every time stay in memory too. Between two fights this saves about 3 to 6
  seconds, depending on how large the four characters are.
- Supported arcade sets: `xmvsf` (Euro 961004), `xmvsfu` (USA 961023), `xmvsfu1d` (USA 961004,
  decrypted; with its parent `xmvsf`).

## How to apply

There is no download of a patched game and no binary patch. The patch is a builder that turns your own
disc image (and, for the restored frames, your own arcade ROM set) into the patched image on your
computer. Nothing from the game is in this repository or in the patcher.

You need your own dump of *X-Men vs. Street Fighter (USA)* in BIN/CUE form, matching the redump.org
entry:

```
X-Men vs. Street Fighter (USA).bin
Size   392393568
CRC32  02cdbe88
MD5    79888a0298937d3db4256fd004b50426
SHA1   c04bf74422c7e1cbb3b961528c38cd67b656856a
```

A `.chd` must be converted back first (`chdman extractcd -i game.chd -o game.cue`). Other regions are
not supported yet.

### The web patcher (easiest)

Open **<https://pepasjc.github.io/xvsf-tag-team/>** (or `patcher/index.html` from a release, saved to
disk) in a desktop browser.

1. Choose your `.bin`. The page checks it before anything else.
2. For the restored frames, also choose your arcade ROM set: `xmvsfu.zip` or `xmvsf.zip`, or
   `xmvsfu1d.zip`; add the parent `xmvsf.zip` too when your set is a clone in split form.
3. Build. A 2 MB image takes about a minute, one with restored frames about four minutes.
4. Save the result: a zip with the `.bin` and the `.cue`.

Everything runs in your browser; your files are never uploaded. On first use the page downloads the
Python runtime it builds with (Pyodide, about 25 MB, from the jsDelivr CDN) and the browser keeps it.
Tested in Chrome and Edge; it needs about 2 GB of free memory for the 8 MB build.

The options: the boot card can be left out, and the button layout can stay the game's own. The page
shows the SHA-1 the result must have before it starts.

### The command line

```
pip install -r requirements.txt
python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --out OUT
python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --arcade xmvsfu.zip --out OUT
```

writes `OUT/X-Men vs. Street Fighter (USA) [Tag Hack 1.0.1].bin` and `.cue` (`[Tag Hack 1.0.1 + Restored
Frames]` with an arcade set). `--chd` also writes a CHD when `chdman` is found. See
[BUILDING.md](BUILDING.md).

### Expected results

The default build (boot card, version line, modern buttons):

```
X-Men vs. Street Fighter (USA) [Tag Hack 1.0.1].bin
Size   392393568
SHA1   2012f9c3ddc8514acc2cca104741b1c15c559bad

X-Men vs. Street Fighter (USA) [Tag Hack 1.0.1 + Restored Frames].bin
with xmvsfu                SHA1   9a208a70f7e6e57ac3a3d2b57154b0fbae3842db
with xmvsf or xmvsfu1d     SHA1   ff5412a7615c052c7a9640b12c77a0b230fd630c
```

Every other combination of options has its own reference in `builder/data/known.json`; both the page
and the command line compare the result with it.

### Turning on 8 MB

- DuckStation and SwanStation (RetroArch): the console option "Enable 8MB RAM".
- MiSTer: the PSX core's 8 MB RAM option.
- A console needs a hardware RAM modification.

The main menu shows "8MB" after the version when the extra memory is in use.

## Compatibility

Tested on a PlayStation with a PSIO (2 MB), a MiSTer (PSX core, 2 MB and 8 MB) and in emulators
(Beetle PSX, SwanStation). The image is a plain MODE2/2352 BIN/CUE and converts to CHD
with `chdman createcd`.

For a PSIO, the `.cu2` sheet must be in PSIO's own format (as written by Cue2cu2 or PSIO's Systems
Console); for this single-track image it is:

```
ntracks 1
size      MM:SS:FF          (length of the .bin: bytes / 2352 sectors, 75 per second)
data1     00:02:00

trk end   MM:SS:FF          (size + 2 seconds)
```

with Windows (CRLF) line endings.

## Known issues

- Moves with very large sprites run slowly. The retail game has the same problem (the port draws
  every sprite through the CPU); the hack aims to match retail speed there, not to exceed it. Keeping
  four full characters costs a little on its own: in the heaviest moves (Sabretooth's super is the
  clearest case) the tag hack runs a few frames per second slower than retail.
- A tag pressed while a move is still finishing is ignored; press again.
- Turbo is off by default, as in the retail game. The arcade's USA default pace corresponds to
  Options → Turbo Speed 2.
- On the heaviest teams and largest stages the 2 MB build has to use a slower sprite encoding for one or
  more characters.
- With restored frames the version line is always shown.

## How it works

The port's executable still contains most of the arcade's tag system, switched off by one mode flag;
the patch turns its parts back on one by one. The hard part is memory: four full characters need about
2.0 MB, and about 1.24 MB is free during a fight. The character sprite files are re-encoded with denser
per-tile codecs and decoded by a routine patched into the game, character code is relocated at load
time so it can sit anywhere, and a new battle loader packs all four characters and picks, per fight, the
fastest encoding that still fits.

The 8 MB build is the same image plus a module that runs only when 8 MB is really present: it keeps
characters in memory between fights, applies the restored frames to each character after loading, and
falls back to the 2 MB path on any doubt. See [docs/architecture.md](docs/architecture.md).

## Documentation

| Document | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How the patch works: codecs, battle loader, tagging, the 8 MB module, restored frames, file cache, speed, the disc |
| [docs/engine.md](docs/engine.md) | Engine reference: objects, the tag system, HUD, match, music, CPU, files, menus |
| [BUILDING.md](BUILDING.md) | Building from source, the options, rebuilding the MIPS code |
| [builder/README.md](builder/README.md) | The build pipeline, stage by stage |
| [patcher/README.md](patcher/README.md) | The web patcher: how it runs, hosting, tests |

## Building from source

Everything the patch is made of is in this repository. Supply your own disc image (and arcade ROM set)
and run the builder, as above. The MIPS parts (battle loader, sprite decoder, 8 MB module, boot card)
are stored compiled, so no cross compiler is needed unless you change them. [BUILDING.md](BUILDING.md)
has the details.

## Repository layout

| Folder | Contents |
|---|---|
| `builder/` | the one-command build (`build.py`) and its pipeline, with the reference hashes |
| `patcher/` | the same build as a single web page (`index.html`), its sources and tests |
| `tools/` | the patch itself: one module per feature (`tagpatch.py`, `hudpatch.py`, `aipatch.py`, …), the disc builders (`mktagdisc.py`, `mkap8disc.py`), sprite formats and codecs (`nsp.py`, `nsppatch.py`), relocation (`reloc.py`) |
| `tools/tagload/` | the 2 MB battle loader (C, MIPS assembly) |
| `tools/nspdec/` | the sprite decoder (MIPS assembly) |
| `tools/ap8/` | the 8 MB boot stub and module (C, MIPS assembly) |
| `tools/ap/` | the restored-frames content builder (reads the arcade ROM set) |
| `tools/logo/` | the boot card |
| `docs/` | the documents above |

## About me

I'm an aerospace software engineer. I lived in Japan for four years and in Germany for five, and I'm
now based in Brazil. This is a hobby project.

## Changelog

[CHANGELOG.md](CHANGELOG.md)

## Reporting bugs

Open an issue at <https://github.com/pepasjc/xvsf-tag-team/issues>. Please say which build (2 MB or
8 MB, ARCADE FRAMES on or off), on what (console, MiSTer, which emulator), the characters and the stage,
and what happened. A screenshot or a short video helps; a freeze, a wrong life bar, missing or broken
sprites, or a fight that runs slower than on the retail disc are all wanted.

## License and reuse

- **Source code** (`builder/`, `patcher/`, `tools/`): [MIT](LICENSE). Use it for anything; keep the
  copyright notice.
- **Documentation** (`docs/`, and the README, BUILDING and CHANGELOG files): [CC BY-NC-SA 4.0](LICENSE-DATA).
- ***X-Men vs. Street Fighter*** — its program, graphics, music and voices — is © Capcom; the X-Men are
  © Marvel. Nothing from the game is in this repository or licensed by it.

Third-party material: zopfli compiled to WebAssembly (`patcher/vendor/zopfli`, npm `@gfx/zopfli`,
Apache-2.0, license included). The page loads Pyodide (MPL-2.0) and numpy from the jsDelivr CDN; they
are not included.

## Credits

- Hacking, tools and documentation: pepa
- Tools used: Beetle PSX, SwanStation, FinalBurn Neo (for comparing with the arcade game), capstone,
  numpy, numba, Pyodide, zopfli, chdman

This is a fan project. It is free, and it must not be sold or bundled with a disc image.
X-Men vs. Street Fighter is © Capcom. X-Men characters © Marvel.
