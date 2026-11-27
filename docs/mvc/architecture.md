# How the patch works

This document describes what the build changes in the game and why. Addresses are RAM addresses of the
USA disc (SLUS-01059); the executable is loaded at 0x80010000. Engine facts the patch relies on are in
[engine.md](engine.md).

## Contents

- [The problem](#the-problem)
- [The 2 MB tag hack](#the-2-mb-tag-hack)
  - [Four full characters in 2 MB](#four-full-characters-in-2-mb)
  - [The battle loader](#the-battle-loader)
  - [Tagging](#tagging)
  - [Special partners](#special-partners)
  - [Arcade behaviour](#arcade-behaviour)
  - [Boot cards and version line](#boot-cards-and-version-line)
- [The 8 MB build](#the-8-mb-build)
  - [One image for both machines](#one-image-for-both-machines)
  - [Memory map](#memory-map)
  - [Characters](#characters)
  - [Restored frames](#restored-frames)
  - [Special partners and effects](#special-partners-and-effects)
  - [The ARCADE FRAMES option](#the-arcade-frames-option)
- [Speed](#speed)
  - [Decode-ahead](#decode-ahead)
  - [VRAM tile cache](#vram-tile-cache)
  - [KO cache](#ko-cache)
  - [SPU RAM as sprite storage](#spu-ram-as-sprite-storage)
  - [Smaller changes](#smaller-changes)
- [Sound](#sound)
- [Menus and options](#menus-and-options)
  - [EX OPTIONS and the card save](#ex-options-and-the-card-save)
  - [VERSUS CPU](#versus-cpu)
  - [ARCADE BALANCE](#arcade-balance)
  - [Achievements](#achievements)
- [PS2 and PS3](#ps2-and-ps3)
- [The disc](#the-disc)
- [Reproducible builds](#reproducible-builds)

## The problem

The arcade game is a tag-team fighter: two characters per side, one on screen, the other on the bench recovering
life, plus a special partner (an assist) called in for one attack. Capcom's port keeps the tag battles only in
CROSS OVER mode, where both players fight with the same two characters: each side's partner is drawn with the
opposing main's data. In Arcade and Versus the partner is loaded as a cut-down set (`PLxx_11.A0`), enough for an
assist or a team super but not to fight; the tag button does nothing.

The tag rules themselves are all in the executable, switched by one flag (`0x8007b75d`, 1 in Arcade and Versus,
0 in Cross Over): the tag move, the four life bars, the KO hand-over, the single round, bench regeneration, the
CPU's team logic. The hard part is memory. A character's code and data are 65-134 KB (X-Men vs. Street Fighter's
are much smaller), its sprite file 360-490 KB in the stock RLE, and four of them need about 1.48 MB even with a
good codec, against about 1.33 MB the battle leaves free. Measured against the other two games, MvC carries about
89 KB of resident code per character (X-Men vs. Street Fighter 55 KB) and 65 KB of tables (its per-frame box data
alone averages 28 KB, against 2.6 KB), so its sprites have about 280 KB less room and need denser, slower codecs.

## The 2 MB tag hack

### Four full characters in 2 MB

Everything is loaded from the disc at the start of a battle and nothing during the fight, as in the stock game.

**Battle RAM** (Versus stage; the pool end moves a few KB per stage):

| Address | Contents |
|---|---|
| up to about `0x800b8d58` | executable, stage, common effects, the GPU primitive pool (capped to what the game really uses) |
| region | special partners first, then the four characters in slot order: P1 main, P2 main, P1 partner, P2 partner |
| below `0x801fd400` | a reserve that the plan never touches: the strong-tier payload, the VRAM cache's image, the winner's frozen sprite at the post-battle loading screen (`0x801fa280`, see below) |
| `0x801fd400` | the decoders and the patch's resident code, copied there after the last disc read |
| `0x801fe800` | the sound swap code |
| top | stack |

Kernel RAM below `0x80010000` that the BIOS leaves unused holds what must survive between battles and scenes: the
gates of every hook, the KO cache, the decode-ahead state, the achievements runtime. Each span was proven free on
real consoles and with every BIOS image tested.

**Sprite codecs.** Each character's sprite file exists on the disc in several encodings, all decoded per tile on
the fly by a dispatcher in front of the game's decoder (`0x8001bd48`); data that is not in a new format takes the
stock RLE path:

| Tier | File size vs stock | Cost per byte (cycles) | Notes |
|---|---|---|---|
| RLE | 1.00 | 8.6 (stock decoder 9.6) | the stock file, faster decoder |
| DSM1 | 0.61 | 33 | context model |
| DSH1 | 0.56 | 89 | Huffman with context classes; DSX = the same data with lookup tables (faster), `hot` variants keep the most decoded tiles as RLE |
| DSR1 | about 0.44 | about 330 | range coder with a static context tree and a run mode (1.8 times faster than its predecessor DSA1 at the same size) |

Tile widths in MvC are any even byte count from 2 to 120, so the codecs code the width and stop at the tile's byte
count; every decoder's output is byte-identical to the stock decoder's, overrun bytes included (checked tile by tile
for every character and tier in a CPU emulator).

**Cut tiers.** The slowest tiers also come in variants in which some frame groups show a near-identical neighbour
group instead (`cut8` to `cut48`: the number of groups). The cuts follow fixed rules (no cut in a move's key
frames or where the character moves) and are the last step the planner takes.

**Per-frame box data (section 3).** Every character file has a section with the box data of each frame. The engine reads it through the main frame table and two inline formats inside the animation data; each
reader site was mapped. The build keeps one copy of every interval the readers can reach and writes a map; a small
remap at the two reader sites (`0x8008dc38`, `0x8008ffc8`) translates the offsets. About 21 KB saved on a heavy team,
exact by construction.

**Frame groups (section 1).** Frame groups are stored packed; the only stock reader, the per-object draw
(`0x8008f68c`), gets them through a small decoder hooked at `0x8008f694`. A character is packed only when that is
cheaper for its whole plan.

**Store-once pairs.** Some characters are variants of another: Red Venom shares 96 % of its decoded tiles with Venom,
Orange Hulk 87 % with Hulk, Lilith 81 % with Morrigan, Gold War Machine 70 % with War Machine, and Chun-Li's tiles
are all inside Shadow Lady's. When both of a pair are in the battle, the loader loads one union sprite file for both.

**Relocation.** Character code is linked to fixed addresses. The disc carries every overlay twice, linked for the P1
and the P2 slot; the difference gives the complete relocation table, so the loader can place a character's code
anywhere (avoiding the few code bases where a `lui` / low-half pair would carry differently).

### The battle loader

`games/mvc/tools/tagload/` (C and MIPS assembly) replaces the slot loop of the Versus / Arcade loader (hook
`0x8002b950` in `0x8002b7a4`). A small resident part reads the loader through a borrowed file-table entry into the
sprite decode arena (`0x80092c40`, idle during the load), checks its word sum and runs it. Then:

1. it reads the directory, which locates every character's files in every tier on the disc;
2. it picks, for the four characters, the special partners, this stage and this sound level, the fastest set of
   tiers that fits. Each tier has a measured decode cost; mains weigh more than partners, and the cut tiers carry a
   penalty. The planner is monotone and exact (it never trades a faster plan for a slower one); in battles with
   special partners a greedy planner keeps the load time down. Every four-character team on every stage fits;
3. it reads each character in slot order: the sound bank, the code with its relocation table (relocated in place,
   then the character's own init routine), the small sprite set whose pixels go to SPU RAM, and the sprite file of
   the chosen tier, registered with the engine's set table;
4. after the last read it copies the decoders and resident code to the top of RAM and loads the two mains' super
   cut-in portraits into the end of the decode arena; a super's cut-in then decodes in bands so that it does not
   overwrite them.

Battles it does not handle (the attract demo, Training, Cross Over, the Onslaught boss fight) take the stock loader
unchanged.

### Tagging

- **Rules.** A battle-init stub (`0x80045fc8`) sets the Versus flag `0x8007b75d` to 0 when the loader loaded four
  full characters; the post-battle phase puts it back. With 0 the game runs its own Cross Over code: tag with HP + HK
  (R1 + R2 by default), the partner jumps in with an attack, four life bars, red life recovered on the bench, one
  round decided by team life, a knocked-out character replaced by the partner. Because MvC switches a tag by
  activating the other object (it does not exchange objects), each object keeps its character for the whole fight
  and the engine's per-character tables, indexed by character id, hold all four side by side.
- **CPU.** The stock CPU never tags: its branch of the tag routine (`0x80055fa8`) waits for an AI command the
  PlayStation CPU almost never issues, then leaves anyway. The patch replaces that branch with a rule on the game's
  own random numbers (`0x8003bc88`) that tags at the arcade's rate, 1-3 tags per 6,000 frames, measured on the arcade
  game in an emulator. The stock veto (busy, in the air, partner knocked out) still applies. In Arcade, where the
  stock CPU team has no partner, the loader gives the CPU a random partner different from the other three.
- **Variable Cross (Duo Team Attack).** The engine has the Duo: QCB + HP + HK at super level 2 or more (team-super
  state 2, `0x80033298`). With four full characters the real tag partner joins the attack. Its two-portrait cut-in
  screen is built for Cross Over (the second portrait comes from the other side's portrait set, the background from
  an image parked in VRAM space that the tile cache uses), so the patch turns the two calls that start it
  (`0x80030650`, `0x8003066c`) into no-ops: the attack starts after the super flash.

### Special partners

Every tag battle also has the special partners, as in the arcade.

- **Load.** The special partners are loaded first in the region, in their own tiers (stock RLE or DSH1-family, with
  some streams in SPU RAM); a partner used by both sides is loaded once. Their one or two sounds each go into spare
  slots of the common sound table.
- **Frames.** A few frames of the largest special partners show a neighbour frame instead (frame-table cuts with the
  same rules as the characters' cut tiers, plus a reach rule that keeps every beam and projectile frame).
- **Choice.** EX OPTIONS **ASSISTS**: ROULETTE, the stock select screen's roulette, which already follows the arcade:
  a button stops it on the highlighted partner, and START with a held button combination picks one by number,
  including the secret Shadow and Sentinel; the patch adds back the reader of those codes (`0x80198aec`). NORMAL picks
  from the grid; OFF leaves them out (more room and speed for the characters).
- **HUD.** The special partner's portrait and its colours (the secret ones included) are uploaded per battle.

### Arcade behaviour

- **Playable Onslaught.** The stock game already has him on a hidden cell, without a partner, on his own stage. The
  patch loads him as a full fighter in Versus and Arcade: in Arcade he fights on the normal stage rotation (the
  stage-9 call sites go through a helper, so a normal stage works), his human damage is scaled for a playable
  fighter, the select screen shows him on his cell, the stage music returns after a KO, a time-over loss no longer
  waits for the stage-9 death scene, and the roulette is skipped. His second form is the CPU boss only. The boss
  fight itself stays stock.
- **Loading screen.** After a match the game draws the winner's frozen sprite into a fixed buffer at `0x801fce00`,
  where the tag hack keeps resident data; the patch points that routine at a reserved buffer.
- **Buttons.** The stock default layout already puts HP and HK on R1 and R2.

### Boot cards and version line

A boot stub at the executable's entry point draws two cards before any game code runs: the PEPA SOFT HOUSE logo,
then a notice that this is a free fan patch, over panels with six select-screen portraits (Spider-Man, Captain
America, Wolverine, Ryu, Mega Man, Strider). The repository holds only the card's own layer; the portraits are
decoded at build time from the user's disc (`SP_SEL4.DSP` and the colours in `SEL01.ARC`). The code and picture live
in the executable's zero area (`0x80100000`-`0x80140000`), which the game clears and uses later; the stub chains to
the game's entry point.

The version line "TAG HACK 1.0" is drawn on the main menu by a stub in the menu file's last-sector slack, hooked at
the end of the menu routine.

## The 8 MB build

Emulators (DuckStation, SwanStation), the MiSTer PSX core and modified consoles can give the PlayStation 8 MB of main
RAM. The arcade ROM set's graphics carry animation frames the port dropped, and its sound ROMs the voices the port
resampled. The 8 MB build uses the extra memory for both.

### One image for both machines

The 8 MB image is the 2 MB image plus appended items: the 8 MB loader, the module, the restored content and the
voice files. A boot stub tests for 8 MB with two patterns written above 2 MB and read back, checking that the address
2 MB lower did not change (a 2 MB machine mirrors its memory, and some emulators return open-bus values instead).
Only when 8 MB is found does it point the battle loader at the 8 MB loader; then it clears itself. On a 2 MB machine
the image is the 2 MB image: the same flags, rows and defaults, checked by playing the same scripted input on both
images in 2 MB mode and comparing every frame's hash.

### Memory map

| Address | Contents |
|---|---|
| `0x80000000`-`0x80200000` | the 2 MB layout, with the character code, sets and special partners as on 2 MB |
| `0x80200000` | the 8 MB module |
| `0x80220000`-`0x80600000` | character sprite files and restored frames (arena, range 0) |
| `0x80600000` | the common voice store (read once per boot) |
| `0x80660000` | the four characters' voice stores (`0x38000` each) |
| `0x80740000`-`0x807d0000` | arena, range 1 |
| `0x807df000`, `0x807e0000` | arena header, voice engine state |

Character code stays in the lower 2 MB: the engine's code does not expect characters above it.

### Characters

Each character's sprite file is the stock file (plain RLE, full resolution, no cuts), read whole into the arena and
registered in place. Files stay in memory between fights and are reused when the same character appears again; when
room is needed, a file the coming battle does not use goes. With every sprite in the fastest format, the 2 MB speed parts
(decode-ahead, the VRAM and KO caches) are not needed and stay off. The effects the 2 MB image draws at half
resolution are full resolution, and the character intros are always the full ones.

### Restored frames

`games/mvc/tools/ap/` builds the content at build time from the user's arcade ROM set (`mvsc`) and the PlayStation
disc:

1. Decode the CPS2 graphics and the arcade program's character and animation tables.
2. Pair every PlayStation animation with its arcade animation, and restore it only when at least two of its frames
   that the port kept are pixel-identical to the paired arcade frames (after the PlayStation's colour reduction):
   two matching poses prove the same action and the same alignment.
3. Convert the arcade frames the port dropped into the PlayStation's sprite format, append them to the stock sprite
   file, and write a record of new frame numbers for the animation tables. Frames that carry hit data are never
   replaced, so every hitbox is stock.

Thousands of animation records get frames back; Roll, Chun-Li and Onslaught already have all of the arcade's.

### Special partners and effects

Every special partner gets the stock frame table back (the 2 MB cuts are undone) and, where the arcade has more
(Thor, for example), its restored frames. Every patch is checked before it is applied: magic, sizes, target
addresses, and the stock values it replaces; anything unexpected means the stock content.

### The ARCADE FRAMES option

On 8 MB the version line reads "TAG HACK 1.0 8MB" and the EX OPTIONS INTRO row becomes **ARCADE FRAMES ON / OFF**
(intros are always full on 8 MB). OFF loads the stock frames and the stock special-partner tables. A 2 MB machine
keeps the INTRO row.

## Speed

The game is CPU-bound in fights: one CPU runs the logic and decodes the sprites, and the stock game already slows
down in some supers with two characters loaded. Four characters on denser codecs need more. The parts below cut the
decode work; each one was checked for exact output, and the speed was measured in Beetle PSX and on a MiSTer.

### Decode-ahead

When a player's frame group changes, the engine decodes every tile of the new group. The patch predicts the next
group from the animation script (the engine already resolves the next record into `+0x34`) and decodes it in the
time the CPU waits while the GPU draws the frame. It runs after DrawSync (overlapping the GPU's own memory traffic
lost speed on hardware), and DSR1 tiles are decoded in row slices so a large tile does not stall a frame. Its
hooks go through kernel-RAM gates that call it only inside a battle the tag loader loaded.

### VRAM tile cache

Decoded player tiles are kept in video memory the battle never uses (x 128-383, y 480-511 and x 960-1023,
y 432-511, about 26 KB, mapped with colour-coded fill probes on every stage and screen). A hit copies the tile with
MoveImage instead of decoding and uploading it. The index is 4-way associative over 256 entries; the cache is
cleared on the first upload outside a fight. In a verify mode every hit was decoded again and compared: no mismatch.
On stage 8 its sunset and night palettes take that VRAM, so the cache is off there and the palettes stay in VRAM.

### KO cache

When a character is knocked out, its sprite memory is free. The survivors' decoded tiles are cached there for the
rest of the fight. On a heavy team after the P2 main's KO (Beetle): walking 28 to 56 loops per second, specials 39
to 54, supers 37 to 51.

### SPU RAM as sprite storage

Each sprite file has streams that are drawn rarely or never in a fight: taunts, intros, win poses, rare KO poses,
up to 24 KB per file. In battles with special partners those streams are stored in free SPU RAM, which lets the
characters use faster tiers. A fake decoder section routes a request for such a tile to a fetch by DMA from SPU RAM
before the decode. The game's own sound library waits for its SPU transfers through the DMA interrupt, so the fetch
masks that interrupt and clears its flag; it also waits for the transfer to finish completely before the decode
starts.

### Smaller changes

- The game's command matcher has a fast path for the common case, and the BIOS memory routines it calls run from RAM
  copies instead of the ROM.
- A few near-identical frames show their neighbour group; checker-patterned panel tiles (War Machine's super) are
  stored filled and masked at decode time, as they compress badly.
- Some effect-only tiles are stored at half resolution and drawn at double size on 2 MB.
- EX OPTIONS **STAGE ANIM OFF** stops the stage background animation; **INTRO SIMPLE** (default on 2 MB) replaces the
  slowest character intros (War Machine's flight, for example) with short ones.

## Sound

Every character of a tag battle, partners included, plays its own full sound bank (`CHRxx_0.SE`); before, a partner
had only the few ids of its cut-down bank. Four full banks do not fit the SPU next to the common bank and the
small sprite sets, so:

- the builder makes every bank at several quality levels from the user's disc (resampled, integer-only, so every
  platform gives the same bytes), and the loader picks the best level that fits each battle;
- the game's sound table has room for 250 entries; the point characters' full lists are registered, the benched
  ones' short lists, and a small swap routine exchanges a side's lists when a benched character needs a sound
  (tags, KO hand-overs, team moves);
- voices get a clarity and loudness correction made at build time (data only: the same sizes, so the same plans and
  the same speed).

**8 MB.** Every voice leaves the SPU banks and is streamed from the extra memory into a pool in SPU RAM when it is
played; effects and looping samples stay resident. With the arcade set, the voices that match an arcade sample use
the arcade's recording at its full length, resampled to 11,681 Hz (the semitone step nearest the arcade's rate):
552 of the 728 voice samples. The Marvel side matches by waveform; the PlayStation's Capcom-side voices are the
arcade takes played about 1.24 times faster at the same pitch, so they were matched with a time-and-pitch fit.

## Menus and options

### EX OPTIONS and the card save

EX OPTIONS is a line in the main menu with its own screen, drawn by code in the last-sector slack of the main menu
file (`OPDEMO.ARC`), so the stock OPTION MODE screen is unchanged. Its rows are STAGE ANIM, INTRO, ACHIEVEMENT POPUP,
ASSISTS, ARCADE BALANCE and INFINITE SUPER METER (each a byte in RAM the patch reads at its own point: at the
battle load, every frame, or at the character pick).

The rows are saved with the game's own option save. The game's 0x500-byte save file has unused bytes inside its
checksummed area; the patch's hooks in the save and load routines (`0x8009ec28`, `0x8009edb8`) write the rows there
with a marker and read them back at boot, and the game's own checksum covers them.

INFINITE SUPER METER holds every fighter, the CPU too, at level 3 (`+0x298`) every frame; achievements are not
evaluated while it is on.

### VERSUS CPU

A main-menu line below VERSUS. The player who confirms it picks both teams; the other side's objects are marked as
CPU (`+3` = 0), so the game's own AI fights, at the OPTION difficulty. The mode stays VERSUS, which is why
achievements do not count. The code sits in executable space the game does not use, and the menu line is added by
the main-menu module of the achievements (below).

### ARCADE BALANCE

An EX OPTIONS row (default OFF) for the two port bugs left once the tag rules run: the meter gain on block and the
red-life minimum, plus the arcade rules for the Onslaught boss fight. A hook in the select screen's code writes the
arcade or the stock words at every character pick. Measurements and the full comparison: [balance.md](balance.md).

### Achievements

The set is listed in [achievements.md](achievements.md). The runtime is the evaluator for RetroAchievements-style
conditions shared by the three hacks, here as a hand-written MIPS core (about 4.3 KB) checked frame by frame against
rcheevos on the compiled set, plus a port layer that derives a 16-byte block every frame: the human side, the first
pick and the character on point, the finish code, the move that landed the KO, the combo counter, full life, the
Arcade clear and whether any of the player's characters fell.

- **Memory.** The core lives in kernel RAM below `0x80010000`, in spans that are unused by every BIOS image tested
  and on the real consoles checked; a copy stub in the executable's zero area places it at boot. One hook, at the
  start of the main frame (`0x80022fe8`), runs the evaluation and the popup.
- **Menu module.** The ACHIEVEMENTS page and the memory card code ride at the end of a copy of `OPDEMO.ARC` (the
  game's file table points at the copy), so the game loads them with the main menu. The core calls them when the
  main menu is up: the page, the menu lines (with ACHIEVEMENTS and VERSUS CPU added) and the card. When the attract
  sequence's second intro loads over the module, the core reads it again before the menu uses it.
- **Memory card.** Its own file (`BASLUS-01059ACH`), written only while the main menu is idle.

The evaluation costs about one scan line per frame in fights; the popup about three while it is shown.

## PS2 and PS3

The PS1 BIOS of a PS2 or PS3 keeps its own tables in kernel RAM (`0x8000A8D0`-`0x8000AD60`, `0x8000B1A0`-
`0x8000B7A8`). The boot stub reads the BIOS date (`0xbfc00100`); on a PS2 or PS3 BIOS:

- the achievements core is not installed, so the menu has no ACHIEVEMENTS or VERSUS CPU line;
- the loader leaves the special partners out, and with them the SPU sprite storage, whose DMA into the RAM mirror
  the PS3's emulator does not handle.

Everything else, the tag battles included, is the same.

## The disc

The game reads files through its own file table in the executable (`0x800255e4`, 8 bytes per file), not the ISO
directory. The build appends new or grown data after the end of the original image (character tiers, the loader,
the directory, the special partners' files, the menu copy, sound levels), with fresh sector headers and EDC/ECC
(mode 2 form 1), and points the file table at it where needed. The image stays a single MODE2/2352 track, about
636 MB (a little more with an arcade set).

## Reproducible builds

`builder/` (`builder/mvcb`) regenerates every intermediate file from the user's inputs and checks the result against
SHA-1 references: the same inputs give the same image on any machine, in the command line and in the browser. The
sprite tiers are rebuilt from the user's disc with the encoders' recorded choices (no model search runs), and every
command of the MIPS toolchain is stored prebaked, so a build needs no compiler. See
[builder/README.md](../../builder/README.md) and [BUILDING.md](../../BUILDING.md).
