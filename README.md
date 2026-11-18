# Tag Team Hacks for Capcom's versus games (PlayStation)

by pepa, 2026

Capcom treated us PlayStation fans really poorly, releasing crippled versions of all their CPS2 fighting games. The
Saturn got a really good port, and even the N64 got a nice fan port, so I thought the PlayStation deserved better.

These patches restore the full 2-on-2 tag team to the PlayStation ports, on a stock console: four complete
characters in every match, tag at any time, the arcade rules.

## X-Men vs. Street Fighter Tag Team Hack 1.3

[![X-Men vs Street Fighter Tag Hack trailer](https://img.youtube.com/vi/aVJAqBGNwyk/maxresdefault.jpg)](https://youtu.be/aVJAqBGNwyk)

- Four full characters, tag with HP + HK, two life bars per side, KO hand-over, a CPU that tags, full sound for
  every character, a rewritten sprite engine.
- New in 1.3: fixes for the bugs reported on 1.2, START skips the end of a won match, an ARCADE BALANCE option
  (the arcade's meter gain and super rules), built-in achievements.
- With 8 MB of RAM and your own arcade ROM set: restored arcade animation frames.

Features, hashes and known issues: **[docs/xvsf](docs/xvsf/README.md)** ·
[changelog](docs/xvsf/CHANGELOG.md) · [achievements](docs/xvsf/achievements.md) ·
[how it works](docs/xvsf/architecture.md)

## Marvel Super Heroes vs. Street Fighter Tag Team Hack 1.0

[![Marvel Super Heroes vs Street Fighter Tag Hack trailer](https://img.youtube.com/vi/ms0N8HAE9A0/maxresdefault.jpg)](https://youtu.be/ms0N8HAE9A0)

- Every Arcade, Versus and Training match becomes a 2-on-2 tag battle with four different, full characters, with
  the tag rules of the game's own Cross Over mode. Every team fits on every stage.
- Full sound banks for partners, secret characters without unlocking, START skip, built-in achievements.
- With 8 MB of RAM and your own arcade ROM set: original sprite quality, characters cached between fights and
  restored animation frames.

Features, hashes and known issues: **[docs/mshvsf](docs/mshvsf/README.md)** ·
[changelog](docs/mshvsf/CHANGELOG.md) · [achievements](docs/mshvsf/achievements.md) ·
[how it works](docs/mshvsf/technical.md)

## How to patch

No patched game is distributed. The patcher turns your own disc image (and, optionally, your own arcade ROM set)
into the patched image on your computer. It recognises the game by itself.

| Game | Disc you need (redump BIN/CUE) | SHA-1 of the `.bin` |
|---|---|---|
| X-Men vs. Street Fighter (USA), SLUS-00627 | `X-Men vs. Street Fighter (USA).bin`, 392,393,568 bytes | `c04bf74422c7e1cbb3b961528c38cd67b656856a` |
| Marvel Super Heroes vs. Street Fighter (USA), SLUS-00793 | `Marvel Super Heroes vs. Street Fighter (USA).bin`, 552,894,048 bytes | `6e50ac0d4dfc5eaf2ddd0da3cabde19e0ec3721a` |

Convert a `.chd` back first: `chdman extractcd -i game.chd -o game.cue`. Other regions are not supported.

### Web patcher

Open **<https://pepasjc.github.io/xvsf-tag-team/>** in a desktop browser (Chrome or Edge). The page is available
in English and Brazilian Portuguese.

1. Choose your `.bin`.
2. Optional, for 8 MB setups: choose your arcade ROM zip (a split clone set takes its parent zip too).
3. Press **Build**, then save the zip with the `.bin` and `.cue`.

There are no other options: the page always builds the release image. Everything runs locally; your files are never
uploaded. The first run downloads about 25 MB of Python runtime. Have about 3 GB of free memory: Marvel Super Heroes vs.
Street Fighter needs about that much, X-Men vs. Street Fighter with restored frames about 2.5 GB.

Offline: download the patcher `.html` from the [releases](https://github.com/pepasjc/xvsf-tag-team/releases) and
open it in the same browsers.

### Command line

```
pip install -r requirements.txt
python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --out OUT
python builder/build.py --disc "Marvel Super Heroes vs. Street Fighter (USA).bin" --out OUT
python builder/build.py --disc "X-Men vs. Street Fighter (USA).bin" --arcade xmvsfu.zip xmvsf.zip --out OUT
```

The command line gives the same images as the page, plus advanced options (no achievements, original button
layout, no boot card, earlier versions, CHD output): see [BUILDING.md](BUILDING.md).

Both the page and the command line check the result against the reference SHA-1 listed on each game's page.

## Compatibility

Tested on a real PlayStation (PSIO), MiSTer (2 MB and 8 MB), PSP / PS Vita (Adrenaline) and in emulators.
PS3 (tested): the games run, achievements switch off automatically; PS2: tested in emulation with a PS2 BIOS (same
behaviour). Details per game: [X-Men vs. Street Fighter](docs/xvsf/README.md#compatibility),
[Marvel Super Heroes vs. Street Fighter](docs/mshvsf/README.md#compatibility).

## Reporting bugs

Open an issue at <https://github.com/pepasjc/xvsf-tag-team/issues> with the game, the build (2 MB or 8 MB, with or
without restored frames), the system, the characters, the stage and what happened. A screenshot or video helps.

## Credits

- Hack, tools, builder and patcher: pepa. Follow me @pepasjc.
- Marvel Super Heroes vs. Street Fighter achievements: adapted from the
  [RetroAchievements set for this game](https://retroachievements.org/game/16340) by **Lowsun**.
- X-Men vs. Street Fighter achievements: written for this hack (RetroAchievements has no set for the PlayStation
  version).
- AI tools were used in this project.
- Thanks to everyone who reported bugs.

## About me

I'm an aerospace software engineer. I lived in Japan for four years and in Germany for five, and I'm now based in
Brazil. This is a hobby project.

## Documentation

- [docs/xvsf/](docs/xvsf/README.md): X-Men vs. Street Fighter: features, [changelog](docs/xvsf/CHANGELOG.md),
  [achievements](docs/xvsf/achievements.md), [ARCADE BALANCE](docs/xvsf/balance.md),
  [how the patch works](docs/xvsf/architecture.md), [engine reference](docs/xvsf/engine.md)
- [docs/mshvsf/](docs/mshvsf/README.md): Marvel Super Heroes vs. Street Fighter: features,
  [changelog](docs/mshvsf/CHANGELOG.md), [achievements](docs/mshvsf/achievements.md),
  [how the patch works](docs/mshvsf/technical.md)
- [BUILDING.md](BUILDING.md): building from source, command-line options
- [builder/README.md](builder/README.md), [patcher/README.md](patcher/README.md)

## License

- Source code (`builder/`, `common/`, `games/`, `patcher/`, `tools/`): [MIT](LICENSE).
- Documentation: [CC BY-NC-SA 4.0](LICENSE-DATA).
- Third party: zopfli (Apache-2.0, included); Pyodide (MPL-2.0) and numpy are loaded from jsDelivr.

This is a free fan project. It must not be sold or bundled with a disc image.
X-Men vs. Street Fighter and Marvel Super Heroes vs. Street Fighter are © Capcom. Marvel characters © Marvel.
