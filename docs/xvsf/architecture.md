# How the patch works

This document describes what the build changes in the game and why. Addresses are RAM addresses of the
USA disc (SLUS-00627); the executable is loaded at 0x80010000. Engine facts the patch relies on are in
[engine.md](engine.md).

## Contents

- [The problem](#the-problem)
- [The 2 MB tag hack](#the-2-mb-tag-hack)
  - [Four full characters in 2 MB](#four-full-characters-in-2-mb)
  - [The battle loader](#the-battle-loader)
  - [Tagging](#tagging)
  - [Arcade behaviour](#arcade-behaviour)
  - [Boot cards and version line](#boot-cards-and-version-line)
- [The 8 MB build](#the-8-mb-build)
  - [One image for both machines](#one-image-for-both-machines)
  - [Memory map](#memory-map)
  - [Characters](#characters)
  - [Restored frames](#restored-frames)
  - [Select screen and effects](#select-screen-and-effects)
  - [The ARCADE FRAMES option](#the-arcade-frames-option)
  - [The file cache](#the-file-cache)
  - [Pre-decoded tiles (1.1)](#pre-decoded-tiles-11)
- [Speed](#speed)
  - [Speed (1.1)](#speed-11)
- [Sound (1.2)](#sound-12)
- [Version 1.3](#version-13)
  - [Fixes](#fixes)
  - [START skips the end of a match](#start-skips-the-end-of-a-match)
  - [ARCADE BALANCE](#arcade-balance)
  - [Achievements](#achievements)
- [The disc](#the-disc)
- [Reproducible builds](#reproducible-builds)

## The problem

The arcade game is a tag-team fighter: two characters per side, one on screen, the other on the bench
recovering life, and either can be called in at any time. The PlayStation has 2 MB of main RAM and 1 MB
of video RAM, about a quarter of what the arcade board works with. Capcom's port loads the two characters
on screen in full and the two partners as a cut-down set: enough to jump in for an assist or a team super,
not enough to fight. The tag button does nothing, and a knocked-out character ends the round.

Most of the arcade's tag system is still in the executable, switched off by one mode flag
(`0x8004278c`, 1 in every PlayStation mode): the tag-out move, the swap of the two objects, the four
life bars, the regeneration of the benched character, the CPU's tag decisions, the music change on a
KO. The patch turns those parts back on one by one. The real work is memory: four full characters are
about 2.0 MB of code and graphics, and about 1.24 MB is free for them during a fight.

## The 2 MB tag hack

### Four full characters in 2 MB

A character is a code overlay (`P/P0/PLxx_10.BIN`, 43 to 66 KB) and a sprite file
(`A/A0/SP_PLxx.NSP`, 219 to 460 KB). The sprite files are where the room has to come from.

- **Sprite codecs.** The port stores each sprite tile run-length coded (RLE). The build re-encodes every
  character's sprite file with denser per-tile codecs and patches a decoder into the game in front of
  its own (the first instruction of the RLE decoder at `0x8001b5b0` jumps to it; data that is not in a
  new format falls through to the original). Two codecs, both decoded per tile on the fly:
  - **XVM1**: a context model with 48 code tables, about 30 cycles per output byte.
  - **XVH1**: Huffman with 256 tables and classes, smaller and about three times slower.
  The decoder (`tools/nspdec/nspdec.S`) lives in executable ranges the game never calls (a debug dump
  and unused library code), checked by filling them with `break` instructions and playing.
- **Tiers.** Each character exists on the disc in four encodings: *base* (XVM1), *mid* (XVM1 with the
  tiles of its long supers kept as plain RLE, so they decode fast), *fat* (more tiles kept as RLE), and
  *strong* (XVH1, the smallest). The tile lists come from measurements of which tiles are decoded in
  bursts (`builder/data/tiles_mid.json`, `tiles_fat.json`).
- **Relocation.** Character code is linked to fixed addresses. The disc carries every overlay twice,
  linked for the P1 slot and for the P2 slot; the difference between the two gives the complete list of
  addresses to fix (`tools/reloc.py`). With it the loader can place a character's code anywhere.

### The battle loader

`tools/tagload/` (C and MIPS assembly) replaces the port's battle loading. It is called from the battle
loader at `0x8002b1ac` and:

1. reads a directory sector (with a checksum) that locates every character's files in every tier;
2. picks, for the four characters of this fight and this stage, the fastest set of tiers that fits
   the memory left by the stage (the policy is modelled in `tools/tagpolicy.py`): base where possible,
   mid or fat for characters with heavy supers when there is room, strong only when nothing else fits;
3. reads the four characters from the top of the heap down, relocates their code, and runs each
   character's own init routine;
4. leaves a debug block at `0x80017350` (what it loaded, where, in which tier).

Nothing is read from the disc during a fight, as before.

### Tagging

- **Tag input** (`tools/tagpatch.py`): a hook in the per-frame player update (the sub-state dispatch at
  `0x80076dd0`) starts the arcade's own tag-out move when HP + HK are pressed. The partner jumps in with
  its attack and the objects are swapped by the game's swap routine (`0x8006b248`). After the
  hand-over the tag is locked for 60 frames, as in the arcade.
- **Full partners**: the per-object "assist only" flag (`+0x74`) that blocks a partner's special moves
  is cleared at round start for full characters, so the incoming character has its whole move set,
  and a KO no longer ends the round when the partner is alive.
- **Palettes** (`tools/palpatch.py`): each object owns fixed colour rows; after a swap they are uploaded
  again for the characters now in them.
- **Life bars** (`tools/hudpatch.py`): the arcade's four-bar HUD, turned back on: the active
  character's bar large, the benched one's small, each with its red (recoverable) part.
- **Regeneration**: only the benched character recovers red life, the arcade rule; the active one only
  shows its red part. A character that tags in, or replaces a knocked-out partner, loses the red part
  it has not recovered.
- **CPU** (`tools/aipatch.py`): the CPU's script interpreter already has tag and assist commands; the
  patch lets the CPU's team moves through, so it tags with the arcade's own logic.
- **Team super and counter assist** need a partner that is still standing.
- **Who stays on point** (1.1, `tools/tagpatch.py`): after a team super (variable combination) and after a
  variable counter, the partner who came in stays on point, as in the arcade. The port's end-of-team-move
  resolver (`0x8006e6f0`) and the counter's effect object (`0x8008dfe8`) chose the "partner leaves" branch by
  the mode flag; both now test the reduced-set mask `0x800421bc` instead, so full partners take the arcade
  branch and the boss fight keeps the port's.
- **Specials after a counter** (1.1): the counter sets the side's bit in `0x80042387` ("assist is out"),
  and only the port's swap-back cleared it. While it was set, the veto routine `0x8006f84c` (asked by the
  command parser, the tag hook and the team moves) blocked every special, super and tag of the new point
  character for the rest of the round. The veto (`0x8006f850`) and the counter stub now skip the bit for
  full partners, as the arcade does.
- **Boss**: Apocalypse has no partner. The player's side keeps both bars and can tag; the boss side has
  one bar.
- **The fight after Apocalypse** (1.1, `tools/hudpatch.py`): the arcade's last fight is the point
  character against its own partner, one character per side. The port mirrors the whole team instead,
  which in the hack became a tag match. In arcade mode with both sides mirrored (that fight only), the HUD
  stub sets both partner objects' life and red life to 0 every frame and hides their bars: tag, team
  super, counter, the CPU's tag and the KO replacement all refuse a partner with no life, so the fight is
  one on one, one round.

### Arcade behaviour

- **One round** (`tools/roundpatch.py`): the match is decided by the team total, the arcade rule; it
  ends when both characters of a side are down, or on time.
- **Music** (`tools/bgmpatch.py`): after a KO the theme of the incoming character starts, as in the
  arcade; a voluntary tag does not change the music.
- **Difficulty** (`tools/diffpatch.py`): the CPU's rank rises during the first fight as in the arcade;
  the port started it at the cap.
- **Balance** (`tools/balpatch.py`): life, damage and regeneration were compared with the arcade program
  and match it; the one difference, the round timer's speed, is set to the arcade's factory setting
  (110 frames per count instead of 100).
- **Buttons** (`tools/padpatch.py`): default layout HP = R1, HK = R2, three punches = L1, three
  kicks = L2, so tag is R1 + R2. The in-game KEY CONFIG still changes it.

### Boot cards and version line

`tools/logopatch.py` draws a boot card from a bare-metal stub at the executable's entry point, before
any game code runs, then jumps to the original entry. `tools/titlepatch.py` adds the version line to the
main menu through a hook at the end of the menu's text routine.

Since 1.1 a second card follows (`tools/card2patch.py`, stub `tools/logo/card2.S`): a notice that this is
a free fan-made patch, with the project's address, over six slanted panels with select-screen portraits.
The repository holds only the card's own layer (`tools/logo/card2.bin`: panel shapes, text and borders).
The portraits are decoded at build time from the user's disc (`SP_SEL0.NSP` and the colours in
`SELECT.BIN`) and composed with that layer into a 15-bit picture in the executable's zero area
(`0x800c0000`). The first card's stub ends in a jump to the second's (`0x800e5800`), which shows the
picture for 4.5 seconds (START or X skips it after one second), clears what it used and jumps to the
game's entry point. The first card now shows only the PEPA SOFT HOUSE logo; with `--nospeed` the build
uses the 1.0.1 card (`tools/logo/card_101.bin`) and no second card.

## The 8 MB build

Emulators (DuckStation, SwanStation, Beetle PSX), the MiSTer PSX core and modified consoles can give
the PlayStation 8 MB of main RAM. The arcade ROM set's graphics carry the animation frames the port
dropped. The 8 MB build uses the extra memory to keep those frames.

### One image for both machines

`tools/mkap8disc.py` builds the 2 MB tag hack first, unchanged, and adds:

- a small boot stub in unused executable ranges (`tools/ap8/ap8boot.c`) at four hooks: the effects
  load and the pool init of the battle loader, the select screen's sprite load, and the main menu;
- the 8 MB module (`tools/ap8/ap8mod.c`, 14 KB) and the restored content, appended after the end of the
  original disc.

Every hook first asks whether 8 MB is really there: it writes test patterns above 2 MB and checks that
they read back and that the corresponding address below 2 MB did not change (a 2 MB machine mirrors its
memory over the 8 MB window). Then the module must be in RAM and intact (magic word and checksum), or
is read from the disc. If either check fails, the hook does exactly what the 2 MB build does. A stock
console plays the same image as the 2 MB tag hack.

### Memory map

| Address | Contents |
|---|---|
| `0x80200000` | the module (12 sectors) |
| `0x80206000` | its state page, the effects undo list (`+0x400`) and the decoder hook `raw_dec` (`+0x1000`) |
| `0x80207800` | the effects sprite file, resident |
| then | shared-slot tables (see below) |
| then | the file cache's resident pack |
| arena | character blocks, from the end of the above to `ARENA_END`; since 1.1 also the pre-decoded tiles |
| `ARENA_END` | scratch: a compressed block being decoded during a battle load; the select screen's sprite files while the select screen runs |

`ARENA_END` and the other boundaries depend on the content and are written into the module's table
by the disc builder, which also checks that the four largest characters fit the arena together.

### Characters

Each character is one block: code overlay with its relocation table, the sprite file (plain RLE, the
fastest to decode), and its patch files. On the disc the whole block is one raw-deflate stream; the
module issues one read and decodes the stream into place while the rest is still coming from the drive
(`tools/ap8/inflate.h`). Blocks stay in memory between fights and are reused when the same character
appears again, after their checksum is verified. When room is needed, the block used longest ago goes.
A block that fails its checksum is read again.

### Restored frames

`tools/ap/` builds the content from the user's arcade ROM set (`xmvsf`, `xmvsfu` or `xmvsfu1d` with its
parent) and the PlayStation disc:

1. Decode the CPS2 graphics and the arcade program's animation tables.
2. Pair every PlayStation animation with its arcade animation: same frame durations, and the frames the
   port kept must be pixel-identical to the arcade's (after the PlayStation's colour reduction).
3. For every frame the port dropped or replaced with a reused one, convert the arcade frame into the
   PlayStation's sprite format and append it to the stock sprite file. The stock frames keep their
   numbers, so an unpatched animation still finds them.
4. Write the patch files the module applies to the character's code after loading:
   - `PLxx.AP8`: new frame numbers for animation records;
   - `PLxx.AD8`: frame numbers stored directly in code (capes, slash trails, beams).
5. **Shared slots.** Some frames are uploaded once and shared by every object that shows them (effects
   drawn several times at once). The game keeps fixed-size tables of those slots; restored content that
   needs more gets a larger table, installed by the module per fight.
6. **Keep-stock lists.** Animations whose restored frames cost speed stay as the port has them. Every
   restored animation was measured with both fighters restored on screen against the stock disc; those
   that pushed the frame rate down by more than one frame per second (average or worst second) are kept
   stock (`builder/data/keep_v3.json`, `tools/ap/aplib.py`).

Restored: Wolverine, Cyclops, Storm, Rogue, Gambit, Sabretooth, Juggernaut, Magneto, Dhalsim, Zangief
and Cammy, three cut sprites of Ryu. Ken, Chun-Li, M. Bison, Akuma, Charlie and Apocalypse keep the
port's frames. Gambit and Magneto are partly restored: their sprite files would exceed the format's
tile numbering.

### Select screen and effects

- **Select screen**: the portraits' animations get their arcade frames back, in two sprite sets (the
  second one is drawn through a small stub that runs from select-screen memory; the module points
  `SELECT.BIN`'s calls at it). Both sets or none.
- **Effects**: the common effects file (`SP_EFF1`) gets restored frames for some families (the
  regeneration sparkle, throw debris, bubbles, rings). Their animation records live in the executable,
  so the module patches them per fight and undoes the patch at the start of every fight, before
  anything else runs. A fight that takes the stock path (the boss on P1's side, a 2 MB machine) sees
  the stock records.

Every patch is checked before the first byte is written: magic, sizes, target addresses, and that each
target still holds its stock value. Anything unexpected means the stock content, unpatched.

### The ARCADE FRAMES option

The module patches the OPTION MODE screen in memory from the main-menu hook. Items 5 to 8 are packed
closer, and a 13th line, ARCADE FRAMES ON / OFF, fits above "PRESS START BUTTON TO EXIT". OFF makes
every hook take the stock content: characters, select screen and effects. The setting lasts until the
console is switched off. A 2 MB machine never runs the module and keeps the stock option screen.

### The file cache

Between two fights the game reloads its select module and the same handful of files every time:
`SELECT.BIN` and its sounds, the portraits, `DEB.SCR`, `SP_SEL1`, `KANJI.TEX`, the common sound bank.
On the 8 MB path the module redirects the game's file loader (`LOADFILE`, `0x8002de3c`):

- **Resident pack** (`AUX.PAK`): seven of those files, raw-deflated by the disc builder from the image
  itself (about 930 KB packed into 260 KB). Read once and kept in memory; each request is decoded
  straight into the game's buffer. It takes the space the four largest characters leave free.
- **Raw copies**: the sound banks and the restored select files are kept as plain copies in free arena
  space when there is room. Characters always win: a copy never displaces a character, and a character
  that needs the space drops copies, lowest priority first.

Every copy is checksummed before use; anything wrong falls back to the disc. The saving depends on how
large the four characters are: about 3 seconds between fights with four large X-Men, about 6 with a
lighter team.

### Pre-decoded tiles (1.1)

At the end of every battle load the module decodes the tiles of the four characters and of the effects
file, with the game's own decoder, into the free memory above 2 MB: each tile as a tagged copy
(`XRAW`, the old offset, the 4 bpp pixels), and the tile's entry in the sprite file's tile table
(section 1) is pointed at it. The order is by measured use: `tools/ap8/hot8.json` scores every tile of
every character by how often it is decoded in play and in burst frames (measured on the 8 MB build with
the restored frames). The disc builder writes that order into each character block as a fifth part
(`PLxx.HT8`), so it comes with the same read. Memory is filled until it runs out; a copy only goes where
its file's 22-bit offsets can reach it, and the opponents' fresh blocks get an equal share of the free
memory behind them. Teams without restored characters fit completely; teams with restored characters get
15 to 48 % of their tiles.

During the fight the decoder hook copies a pre-decoded tile instead of decoding it, and the upload loops
send it to video memory straight from the copy. A tile that was not pre-decoded is copied into the space
left over the first time it is decoded. Every redirection is undone from the copies' headers before the
next battle load, effects load, `LOADFILE` and select screen, so the stock files are intact whenever the
game reads them. The decode adds 0.85 to 1.2 seconds to a battle load. Supers with restored frames
lose far fewer frames (Chun-Li's Kikoshou: 53.8 to 56.6 loops per second on average).

## Speed

The port is CPU-bound in fights: the one CPU runs the game and decodes every sprite every frame. Large
sprites (supers, Juggernaut, Apocalypse) slow the retail game down too.

- The 2 MB hack must fit four characters, so it cannot always use the fastest encoding; the loader picks
  the fastest set that fits each fight.
- The 8 MB build uses plain RLE everywhere. Its restored content was measured scenario by scenario
  (idle, walking, normals, specials, supers, dashes, both players at once, 16 teams) against the stock
  disc; the keep-stock lists hold what did not stay within one frame per second.
- Some slowdown comes from the tag hack itself (four full characters, the tag code). It shows in the
  2 MB build too and does not depend on the restored frames.

### Speed (1.1)

1.1 replaces the hot paths of the sprite pipeline and a few engine routines with hand-written MIPS that
computes the same results (`tools/speed/`, one entry point `tools/speedpatch.py`; `--nospeed` gives the
1.0.1 image bit for bit). Each module rewrites whole functions inside their original address ranges or in
executable ranges that nothing references.

| Module | What it replaces | Effect |
|---|---|---|
| `decode` | the RLE tile decoder `0x8001b5b0` and the hack's XVM1 / XVH1 decoders | cycles per byte (Beetle): RLE 8.8 to 7.4, XVM1 30.4 to 25.9, XVH1 95 to 82 |
| `upload` | the sprite memory (arena) allocator `0x80058d04`, the end-of-frame sweep, the three upload loops `0x8005935c` / `0x80059564` / `0x80059930` | fewer allocator flushes, shorter loops |
| `quad` | the sprite-part primitive builder `0x80056340` and the frame-record parsers `0x80057be4` / `0x80057f48` | 1330 to 555 cycles per part; the hot loop fits the instruction cache better |
| `frame` | the sprite-list dispatcher and walkers, layer dispatch, draw and present, libgpu's queue (`_addque`, `_exeque`, the timeout check), the BIOS memory routines, the stages' background layers | see below |
| `logic` | the draw-list insert `0x800303f0`, the move parser's command matcher `0x8007d100` (fast path without a stack frame) | a few thousand cycles per frame |

The `frame` module in detail: `bcopy`, `bzero`, `memcpy` and `memset` under 1 KB run from RAM instead of
the BIOS ROM (larger ones keep the BIOS routine, whose timing the attract demo relies on). The libgpu queue
functions are rewritten register for register, because the game reads registers that libgpu calls leave
behind (the score code `0x80075550` ORs one of them into a player byte). When the GPU is still busy with
the screen clear, the first draw of a frame is queued instead of waited for, and a root-counter interrupt
starts the queue as soon as the GPU is free. On stages whose background code allows it, the next frame's
background layers are built while the GPU draws this frame's sprites. The stages' background tile layers
(compiled per stage in `P/P4/STAGEn.BIN`) are rewritten too: four compiled templates are matched word by
word in every stage file and emitted again with the values in registers (`bgtile.py`), seven one-off
variants are rewritten individually (`bghand.py`); these patches go into the stage files on the disc.

The strong tier (XVH1, the slowest decoder) now keeps each character's most decoded tiles as plain RLE,
up to 4 KB per character (`builder/xvb/strongrle.py`, `builder/data/hot_tiles.json`): 24 to 47 % of a
strong character's decode volume takes the fast path. The battle loader's directory read is three sectors
instead of one; the two extra sectors carry a decode-ahead predictor that follows the animation scripts.
It has no consumer in 1.1; the cache it was written for comes later.

**How equivalence was checked.** Every rewritten function was run against the original in a CPU emulator
(Unicorn) on real calls captured from fights and on random mutations of them, comparing all of RAM, the
scratchpad, the return values, the saved registers and the log of outside calls (thousands to tens of
thousands of calls per module, no difference). All of the new code passes a load-delay hazard check for
the R3000. Then the built discs were compared with 1.0.1 in Beetle PSX, one disc per process, every logic
frame locked to five vblanks, same inputs: the displayed picture and the game state
(`0x80042000`-`0x80044000`) per logic frame, over 3,400 to 4,300 logic frames in each of four scenarios
(strong tier, Chun-Li's Kikoshou, Magneto, Storm; specials, supers, tags, a KO and the replacement). No
picture differs. The only state difference is a byte the stock game itself sets from a leftover register
(`P+0x117`, see above); a timing-only change to the stock game flips it the same way. The speed build was
also played on a real PlayStation before the release.

Result on a stock 2 MB console (Beetle, 10 teams in 12 situations, loops per second): situations below
full speed went from 98 of 120 in 1.0.1 to about 65; walking, normals and most specials run at full speed
with four characters loaded. The original
game, with two characters and no tag, has 41 of 110 below full speed in the same test.

**Prebaked code.** All of the patch's own MIPS code, the speed modules and the stage patches included, is
stored assembled in `builder/data/blobs/` (one file per piece, named by its SHA-1 and checked on every
read; `manifest.json` maps each code-generating function and its arguments to its piece). The builder
and the web patcher install these in place of the generating functions and run no compiler or other
program. Where a piece keeps some of the game's own instructions, the blob stores a reference (file,
offset, length) instead of the words, filled in from the user's disc. [BUILDING.md](../../BUILDING.md)
describes re-baking them after a source change.

**Not enabled.** A frame cache that keeps decoded sprite frames in the arena between frames (`UP_FC`,
`tools/speed/upload/fcache.c`) froze on a real console after several attract-mode cycles. It is off; the
source is included.

## Sound (1.2)

The port loads five sound banks per battle: the common bank `XS_MAIN` and, per side, the main
character's full bank (`CHRxx`) but only a small `HELPxx` bank for the partner. A partner tagged in
therefore lost most of its voices and effects. 1.2 loads the full bank of every character in the fight.

- **SPU budget.** Stock samples fill SPU RAM 0x1010-0x68000 (421,872 bytes); the battle stores the
  `A/A2/SP_EFF2.NSP` pixel data (the FIGHT banner, super cut-in portraits) above it and reads it back tile
  by tile. SPU 0x7EA80-0x80000 holds the finish-effect palettes, written once at boot and read back at every
  KO or super finish: it stays untouched. On 2 MB the samples now use 0x1010-0x70CC0 (457,904 bytes) and the
  `SP_EFF2` data moves up to 0x70CC0-0x7EA80. On 8 MB the `SP_EFF2` data stays in main RAM (0x801F0000, unused on the
  8 MB path), so the samples use 0x1010-0x7EA80 (514,672 bytes).
- **Banks.** Each character bank is rebuilt from the disc's `CHRxx` with the ids only its `HELPxx` had,
  ids the character requests but no bank had (Juggernaut's KO scream, Akuma's Gou Hadouken), and alias
  tones for the tag voices (their samples are already in the bank under another id, so they cost no SPU
  memory). `XS_MAIN` drops the round-announcer voices the hack never plays.
- **Quality levels, made at build time.** Four characters' full banks do not always fit. The builder makes
  every bank at several levels from the user's disc (`tools/sndpatch.py`, `tools/snd/`): level 0 is the
  original ADPCM data; 2 MB levels 1 to 3 resample every sample above 20,000 / 17,000 / 14,800 Hz down
  to that rate (windowed sinc) and re-encode it (search ADPCM encoder), with the pitch raised by the same
  ratio. Both are integer-only, so every platform and the browser give the same bytes.
- **Per-battle choice.** A sound directory (3 sectors in `DMY.DAT`, code and tables from
  `tools/snd/snddir.c`) is read before the banks of each battle; it picks the best level pair for
  `XS_MAIN` and the characters that fits the budget. On 2 MB every team of four different characters
  needs a level above 0; smaller teams fit at level 0 or close to it.
- **8 MB.** Level 4 = level 0 plus the arcade samples the PlayStation has no sound for (Wolverine's third
  tag voice, taken from the user's arcade set by `tools/ap/snd8build.py`); level 5 caps samples at the
  arcade's 24,038 Hz. 2,117 of the 2,380 four-character teams play the original samples unchanged.

## Version 1.3

### Fixes

- **Tag after a team super or variable counter.** The tag hook fired on any *change* of HP + HK, so releasing
  the buttons after holding them through the move tagged the new point character back out. The hook in
  `tools/tagpatch.py` now reacts to a new press only.
- **HUD portrait.** The routine at `0x8007f614` picked the partner portrait from the object's assist field
  (`+0x74`), which a tag does not update; it now uses `+0x230` (`tools/hudpatch.py`).
- **Apocalypse from controller 2.** With the human on pad 2, Apocalypse took player 1's character slots in
  the stock boss setup, and the battle loader then loaded the human partner as an assist set (no tag). The
  loader's boss preparation (`tools/tagload/tagload.c`, `bossprep`) now handles that side, and both human
  characters load in full.
  The 1.2 loader is kept in `tools/tagload/r12/` for the `--nospeed` / `--nosound` builds, so those still give
  the 1.0.1 and 1.1 images bit for bit. The 8 MB module still declines that one fight; the 2 MB loader runs it.

### START skips the end of a match

`tools/skippatch.py` hooks the game proper's per-frame dispatch (`0x80028648`, `jal 0x80028dc8`) in Arcade and
Versus, for human pads only. Once a match is decided (match phase 10 or later, result set), a START press
latches: the win-pose timers of phases 12 and 14 are zeroed (the round and match bookkeeping of phases 16 and 18
runs as usual), and in the after-match scene (12) the win-quote overlay is moved to its own exit state, so the
game's grid / continue decisions are untouched. Opponents, stages, the boss fights and the score are the same as
without the skip. The stock "free move after the KO" moved from START to SELECT. The code lives in kernel RAM the
BIOS leaves unused (`0x80007880-0x80008000`, with the ARCADE BALANCE option), copied there at boot by a stub in
the executable's zero area that chains to the previous entry point.

### ARCADE BALANCE

An OPTION MODE line that switches the two gameplay gates of the port's "PS1 mode" flag to their arcade branch:
meter gain (`0x80075144`) and the super start check (`0x8007d628`). Measurements and the full comparison:
[balance.md](balance.md).

### Achievements

The set is listed in [achievements.md](achievements.md). The runtime is an evaluator for RetroAchievements-style
conditions (checked against rcheevos on the compiled tables) plus a small port layer that derives a block of
bytes every frame: the human side, the team, the character on point (the tag swap moves characters between the
objects, so the main object is always the one on point), the combo counter, KOs, wins and the Arcade clear.

- **Memory.** The code and data live in kernel RAM below `0x80010000` that the BIOS leaves unused, split into
  several spans that were zero at boot and never written on the emulators, BIOS images and the real consoles
  checked. A copy stub in the executable's zero area places them at boot.
- **Boot guard.** Before copying, the stub fills the spans with a pattern, waits about 90 ms and checks it. If
  anything wrote there (a PS2 or PS3 in PS1 mode, some loaders), it restores the old contents, hooks nothing and
  the game runs as stock. A watchdog then sums the read-only part of the runtime, a little each frame; a
  difference switches the achievements off.
- **Hooks.** The frame routine (popup), the frame's present before `DrawSync` (evaluation and card work) and the
  main-menu routine (the ACHIEVEMENTS item above OPTION MODE and the page). The main-menu overlay is patched in
  RAM when it loads.
- **Memory card.** Its own file (`BASLUS-00627ACH`), written only from the main menu's idle state. Without a
  usable card the menu shows a notice once, popups read "UNLOCKED (NOT SAVED)", and the menu checks the card
  again every few seconds.

The cost is below one scan line per frame for the evaluation; the popup costs about 2 % of a frame while it is
shown.

## The disc

The game reads files through its own file table in the executable (`0x8003d91c`, 8 bytes per file),
not the ISO directory. The build rewrites files in place when they shrink and appends new or grown data
after the end of the original image, with fresh sector headers and EDC/ECC (mode 2 form 1). The
character files of all tiers are re-laid in one extent in the order the loader reads them, which also
shortens seeks. The image stays a single MODE2/2352 track.

## Reproducible builds

`builder/` regenerates every intermediate file from the user's inputs and checks the result against
SHA-1 references (`builder/data/known.json`): the same inputs give the same image on any machine, in
the command line and in the browser. Everything that needs a MIPS compiler (the loader, decoders, speed
modules, stage patches, 8 MB module, boot cards, version line) is stored compiled in `builder/data/blobs/`,
so a build needs no compiler; changing a source needs the compiler again. See [BUILDING.md](../../BUILDING.md).
