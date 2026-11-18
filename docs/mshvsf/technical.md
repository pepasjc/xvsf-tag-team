# Marvel Super Heroes vs. Street Fighter Tag Hack: how it works

Technical notes on the 1.0 patch. Addresses are RAM addresses of the USA disc (SLUS-00793). Much of the method is
shared with the X-Men vs. Street Fighter hack ([docs/xvsf/architecture.md](../xvsf/architecture.md)); this page
covers what is different in this game.

## Contents

- [The tag rules: one flag](#the-tag-rules-one-flag)
- [Four full characters](#four-full-characters)
- [Sprite codecs](#sprite-codecs)
- [Speed](#speed)
- [Sound](#sound)
- [Secret characters, training and menus](#secret-characters-training-and-menus)
- [START skip and achievements](#start-skip-and-achievements)
- [8 MB](#8-mb)
- [The builder](#the-builder)

## The tag rules: one flag

MSHvSF's CROSS OVER mode is the arcade tag-team game, and every difference between it and the other fight modes
reads one byte, `0x800250c7` ("partners are assist-only"). The menu sets it on mode entry: 1 for Arcade, Versus,
Training and Hero Battle, 0 for Cross Over. It plays the role of X-Men vs. Street Fighter's PS1-mode flag, with one
difference: here the value 0 is a shipped, fully working mode. So the gameplay needs one patch: at battle init
(after the battle loader, before match init), set the flag to 0 when every partner is loaded in full in Arcade,
Versus or Training. Tagging, the four life bars, red-life recovery on the bench, KO replacement, the single round,
the CPU's tag logic, Variable Counter and Variable Combination and the music change are then the game's own Cross
Over code. The stub runs once per battle and adds no work per frame. The attract demo keeps its stock rules.

## Four full characters

A character is a code and data file (`PLxx_10.A0`) and a sprite file (`SP_PLxx.DSP`, about 440 KB on average).
Four stock characters need about 1.7 MB of sprites alone; a fight has room for far less. The battle loader
(replacing the stock one through a hook in the battle-scene init) reads all four characters, relocates their code
into the free memory of the fight, and picks per character the fastest sprite encoding that still lets the whole
team fit on that stage.

Every one of the 235,313 team and stage combinations, secret characters and Apocalypse included, was checked
against a model of the loader's memory plan. The floors, in order:

1. the base codec everywhere (about 134,000 teams need no more);
2. the strong codec (about 99,500 more);
3. the partners' animation-patch sets stored in sound RAM instead of main RAM (1,748 teams);
4. for 168 teams (0.071 %), one character of the team gets a cut version of the strong tier: tiles that were never
   decoded in measured play are blanked.

So the loader never falls back to a cut-down partner.

## Sprite codecs

The stock decoder at `0x8001bd68` is replaced in place by a dispatcher that recognises three formats:

| tier | format | sprite pixels vs stock | decoder |
|---|---|---|---|
| fast | the stock RLE file | 1.00 | rewritten RLE, faster than stock |
| mid | DSM1 with the most-decoded tiles kept as RLE | 0.55 to 0.61 | both |
| base | DSM1 | 0.54 | in the executable |
| strong | DSH1 | 0.48 | loaded per battle at `0x801fe200` |

DSH1 is the port of the X-Men vs. Street Fighter strong codec: 4-bit pixels in raster order, canonical Huffman
codes chosen by the neighbouring pixels' context, plus copy-from-above runs. Every tile of all 37,695 sprite tiles
decodes to the same bytes as the stock decoder. The files are re-encoded on the user's computer at build time; the
repository holds only the encoders.

## Speed

Stock MSHvSF draws two full characters; the hack draws four, with slower encodings. The speed work:

- the BIOS memory copy and clear routines moved into RAM, and the sprite part and tile header parsers rewritten;
- **decode-ahead:** the engine already pre-decodes the predicted next frame of each object, but synchronously.
  The hack keeps that engine work at the stock time and only defers the tile decodes into the idle time before
  the vertical blank, finishing them at once when a block is about to be used. The predictor also follows
  animation jumps and checks effect objects during supers, so more frames are ready in time;
- a SPEED METER option (OPTION MODE) shows the frame rate for tests on hardware.

Every piece of new code went into ranges proven unused (no reference from the executable or any code file on the
disc, and trap-fill tests through boot, attract, fights and the ending).

## Sound

In the original, a partner only had a small helper bank (3 to 11 assist sounds): after a tag or a KO hand-over most
of its moves, its tag voice and its KO scream were silent. The hack gives every character of a tag battle its own
full bank. Four stock banks need about 370 KB; sound RAM has about 240 KB for them. So:

- win-quote voices (never requested in a fight) are left out of the fight banks;
- the common bank is rebuilt for the fight in the same budget;
- per battle the loader takes the first level of a ladder that fits: sound effects are resampled to lower rates
  first (down to 3.7 kHz), voices only after that.

Over all four-character teams, voices keep the original samples in 99.7 % of teams (the rest at 7.8 / 7.4 kHz);
teams of three characters keep everything. The samples are decoded, resampled and re-encoded from the user's disc
at build time with the same integer-only resampler and ADPCM encoder as the X-Men vs. Street Fighter hack.

## Secret characters, training and menus

- Holding SELECT while confirming a character picks its secret version (Cyber-Akuma, Mech-Zangief, Dark Sakura,
  Shadow, U.S. Agent, Mephisto, Armored Spider-Man), as main or partner; SELECT six times on Akuma picks
  Apocalypse. Cyber-Akuma fights solo, as in the arcade.
- Training: the dummy side picks a partner, and the fight uses the tag rules.
- CROSS OVER is removed from the main menu; OPTION MODE gets SPEED METER (and ARCADE FRAMES on 8 MB); the main menu
  shows the version line.
- The default buttons need no patch: the stock layout is already HP = R1, HK = R2, 3P = L1, 3K = L2.

## START skip and achievements

Both work as in the X-Men vs. Street Fighter hack ([architecture.md](../xvsf/architecture.md#version-13)): a
START press after a won match moves the win quote to its own exit and skips the map, and the achievements runtime
(the same evaluator, with a port layer for this game) lives in kernel RAM the BIOS leaves unused, behind a boot
check that switches it off when something else uses that memory. The set: [achievements.md](achievements.md).

## 8 MB

Images built with an arcade ROM set (or `--ram8`) carry the 8 MB loader. At the first main-menu frame a probe
checks for 8 MB: first a read-only mirror test (a 2 MB console mirrors its
RAM, so nothing above 2 MB is ever written there), then a write and read-back. Without 8 MB the 2 MB loader runs
unchanged. With 8 MB:

- all four characters run from upper RAM in the stock sprite format (no slower encodings);
- a file cache from `0x80271000` keeps characters between fights (least recently used first, checked by a word sum
  on reuse), so loading is shorter;
- the full-quality sound banks are used;
- with an arcade ROM set, a character's animation records whose PlayStation frame is not its
  arcade sprite get a new frame converted from the arcade graphics at build time; the loader points the game at
  the extended frame table. ARCADE FRAMES OFF in OPTION MODE loads the stock files instead (from the next fight).

## The builder

`builder/build.py` recognises the game from the files on the disc (`builder/games.py`) and hands MSHvSF to
`builder/mshb`. As for X-Men vs. Street Fighter, the input is checked by SHA-1, all of our MIPS code is stored
compiled in `builder/data/mshvsf/blobs/` with the game's own instructions stored as references filled in from the
user's disc, the sprite tiers and sound levels are encoded at build time, and the result is checked against the
reference SHA-1 (`builder/data/mshvsf/known.json`). See [BUILDING.md](../../BUILDING.md).
