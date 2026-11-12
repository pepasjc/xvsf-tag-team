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
  - [Boot card and version line](#boot-card-and-version-line)
- [The 8 MB build](#the-8-mb-build)
  - [One image for both machines](#one-image-for-both-machines)
  - [Memory map](#memory-map)
  - [Characters](#characters)
  - [Restored frames](#restored-frames)
  - [Select screen and effects](#select-screen-and-effects)
  - [The ARCADE FRAMES option](#the-arcade-frames-option)
  - [The file cache](#the-file-cache)
- [Speed](#speed)
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
- **Boss**: Apocalypse has no partner. The player's side keeps both bars and can tag; the boss side has
  one bar.

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

### Boot card and version line

`tools/logopatch.py` draws a boot card from a bare-metal stub at the executable's entry point, before
any game code runs, then jumps to the original entry. `tools/titlepatch.py` adds the version line to the
main menu through a hook at the end of the menu's text routine.

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
| `0x80200000` | the module (7 sectors), then its state page (`0x80203800`) and the effects undo list (`0x80203c00`) |
| `0x80205000` | the effects sprite file, resident |
| then | shared-slot tables (see below) |
| then | the file cache's resident pack |
| arena | character blocks, from the end of the above to `ARENA_END` |
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

## The disc

The game reads files through its own file table in the executable (`0x8003d91c`, 8 bytes per file),
not the ISO directory. The build rewrites files in place when they shrink and appends new or grown data
after the end of the original image, with fresh sector headers and EDC/ECC (mode 2 form 1). The
character files of all tiers are re-laid in one extent in the order the loader reads them, which also
shortens seeks. The image stays a single MODE2/2352 track.

## Reproducible builds

`builder/` regenerates every intermediate file from the user's inputs and checks the result against
SHA-1 references (`builder/data/known.json`): the same inputs give the same image on any machine, in
the command line and in the browser. The parts that need a MIPS compiler (the loader, decoder, module,
boot card) are stored compiled in the repository (`tools/**/*.bin`, `builder/data/toolcache/`), keyed by
a hash of their sources; changing a source needs the compiler again. See [BUILDING.md](../BUILDING.md).
