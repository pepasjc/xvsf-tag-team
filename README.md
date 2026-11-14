# X-Men vs. Street Fighter: Tag Team Hack (PlayStation)

**Version 1.2**, 2026, by pepa

Capcom treated us PlayStation fans really poorly, releasing crippled versions of all their CPS2
fighting games. The Saturn got a really good port, and even the N64 got a nice fan port, so I thought
the PlayStation deserved better.

This patch restores the full 2-on-2 tag team to the PlayStation port, on a stock console. With 8 MB of
RAM (modded console, MiSTer or emulator) and your own CPS2 ROM set, it also restores the arcade
animation frames the port cut.

## What it does

- All four characters loaded in full, no disc access during a fight.
- **Tag** at any time with **HP + HK**: the partner jumps in with an attack and takes over, with its
  full move set.
- One life bar per character; only the benched character recovers red life.
- A knocked-out character is replaced by its partner. One round; the match ends when both characters
  of a team are down.
- The CPU tags on its own, using the arcade logic. Tagging also works against Apocalypse.
- After a team super or a variable counter, the partner who came in stays on point.
- The fight against your own partner after Apocalypse is one on one.
- Music switches to the incoming character's theme after a KO.
- Arcade difficulty ramp and timer speed.
- Default buttons: HP = R1, HK = R2, three punches = L1, three kicks = L2 (tag = R1 + R2). KEY CONFIG
  still changes them.
- Faster battle loading, and a rewritten sprite engine: full speed in normal play, with far less
  slowdown in supers.
- Every character has its full set of voices and sound effects, partners included, and the tag voices
  play. On 2 MB, teams of four different characters use slightly lower sample rates to fit.

## Restored frames (8 MB)

- **Restored:** Wolverine, Cyclops, Storm, Rogue, Gambit (partly), Sabretooth, Juggernaut, Magneto
  (partly), Dhalsim, Zangief, Cammy, three Ryu sprites, the character select screen and some common
  effects.
- **Not restored:** Ken, Chun-Li, M. Bison, Akuma, Charlie, Apocalypse.
- Used only when 8 MB is present: the main menu shows "8MB", and OPTION MODE gets **ARCADE FRAMES
  ON / OFF**. On a 2 MB console the same image plays as the normal tag hack.
- Characters and menu files stay in memory between fights, so loading is shorter.
- Full sound quality for almost every team, plus Wolverine's tag voice from the arcade set.
- Supported arcade sets: `xmvsf` (Euro 961004), `xmvsfu` (USA 961023), `xmvsfu1d` (with its parent
  `xmvsf`).

Turning on 8 MB: "Enable 8MB RAM" in DuckStation or SwanStation, the 8 MB RAM option of the MiSTer PSX
core, or a hardware RAM mod on a console.

## How to apply

No patched game is distributed. The builder turns your own disc image (and, optionally, your arcade ROM
set) into the patched image on your computer.

You need *X-Men vs. Street Fighter (USA)* as BIN/CUE, matching redump.org:

```
X-Men vs. Street Fighter (USA).bin
Size   392393568
SHA1   c04bf74422c7e1cbb3b961528c38cd67b656856a
```

Convert a `.chd` back first: `chdman extractcd -i game.chd -o game.cue`. Other regions are not
supported.

### Web patcher

Open **<https://pepasjc.github.io/xvsf-tag-team/>** in a desktop browser (Chrome or Edge).

1. Choose your `.bin`.
2. Optional: choose your arcade ROM zip (plus the parent `xmvsf.zip` for a split clone set).
3. Build, then save the zip with the `.bin` and `.cue`.

Everything runs locally; your files are never uploaded. The first run downloads about 25 MB of Python
runtime. The 8 MB build needs about 2.5 GB of free memory.

### Command line

```
pip install -r requirements.txt
python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --out OUT
python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --arcade xmvsfu.zip --out OUT
```

See [BUILDING.md](BUILDING.md) for the options.

### Expected results

```
[Tag Hack 1.2].bin                       SHA1  a296224a6ca784982c4f0cc9fb02761f0b79bffe
[Tag Hack 1.2 + Restored Frames].bin
  with xmvsfu                            SHA1  667e2dfe23a6f845a41cc1d9cd74e3e48bf526e6
  with xmvsf or xmvsfu1d                 SHA1  edc180c91d74d315b21030291f53ff2bc60cd99e
```

Both the page and the command line check the result.

## Compatibility

Tested on a real PlayStation (PSIO), MiSTer (2 MB and 8 MB), Beetle PSX and SwanStation.

## Known issues

- Some supers with very large sprites can still slow down on 2 MB.
- A tag pressed while a move is still finishing is ignored; press again.
- Turbo is off by default, as in the retail game. The arcade's USA pace is Turbo Speed 2.

## Documentation

- [docs/architecture.md](docs/architecture.md): how the patch works
- [docs/engine.md](docs/engine.md): engine reference
- [BUILDING.md](BUILDING.md): building from source
- [CHANGELOG.md](CHANGELOG.md)

## Reporting bugs

Open an issue at <https://github.com/pepasjc/xvsf-tag-team/issues> with the build (2 MB or 8 MB),
the system, the characters, the stage and what happened. A screenshot or video helps.

## About me

I'm an aerospace software engineer. I lived in Japan for four years and in Germany for five, and I'm
now based in Brazil. This is a hobby project.

## License

- Source code (`builder/`, `patcher/`, `tools/`): [MIT](LICENSE).
- Documentation: [CC BY-NC-SA 4.0](LICENSE-DATA).
- Third party: zopfli (Apache-2.0, included); Pyodide (MPL-2.0) and numpy are loaded from jsDelivr.

This is a free fan project. It must not be sold or bundled with a disc image.
X-Men vs. Street Fighter is © Capcom. X-Men characters © Marvel.
