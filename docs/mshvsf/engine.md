# Engine reference

What the patch relies on in *Marvel Super Heroes vs. Street Fighter* for the PlayStation, USA (SLUS-00793). RAM
addresses; the executable `SLUS_007.93` is loaded at `0x80010000` (entry `0x800106e0`). Overlays (the main menu
`OPDEMO.BIN`, the select screen, stages) are loaded at `0x80094800`. How the patch uses all this is in
[technical.md](technical.md); the X-Men vs. Street Fighter counterpart is [docs/xvsf/engine.md](../xvsf/engine.md).

These are working notes, verified as far as the patch needed them; anything not listed here was not looked at.

## Disc

- All game data is in `DAT/`. Characters: `PLxx_10.A0` / `PLxx_20.A0` (full code and data, P1 and P2 copies,
  150-195 KB; the two differ only in relocations, about 1.2% of the bytes) and `PLxx_11.A0` / `PLxx_21.A0` (the
  cut-down assist partner, 60-97 KB). Sprites `SP_PLxx.DSP` (410-480 KB). Music `XA/MS0x.XAP`.
- File table `0x80024600`: 8-byte entries (u32 size, BCD MSF, 0).
- `.A0` files: u32 section count, then the section offsets.

## Characters and objects

- Team ids `0x800707ea`: 4 × u16 character id × 2 (P1 main, P1 partner, P2 main, P2 partner), written by the
  select screen. `0x80070538`: 4 × u8 ids of the characters currently loaded (the loader's cache).
- Player objects, 0x3c0 bytes each (X-Men vs. Street Fighter: 0x348): P1 `0x80070b50`, P2 `0x80070f10`,
  P1 partner `0x80071310`, P2 partner `0x800716c8`. Fields used:

| Offset | Meaning |
|---|---|
| `+0x03` | human / CPU flag |
| `+0x4e` | character id × 2 |
| `+0xbc` | opponent object |
| `+0x250`, `+0x2c8` | per-character pointers |
| `+0x254` | life (full = 0x90) |
| `+0x25e` | recoverable (red) life |
| `+0x262` | is the partner object |
| `+0x264` | other team member's character id × 2 |
| `+0x268` | partner object |
| `+0x294` | score (player 1) |

Many fields sit 0x30 higher than in X-Men vs. Street Fighter (life `+0x254` there `+0x224`).

## Modes and the tag switch

- `0x800250c7` (= `0x80025040 + 0x87`): "partners are assist-only". The menu sets it on mode entry: 1 for BATTLE
  (arcade), VERSUS, TRAINING and HERO BATTLE, 0 for CROSS OVER. With 0 the engine runs the arcade tag rules: tag
  with HP+HK (`0x80041b50`), four life bars, KO hand-over (`0x8003cf24`), one round, team life decides, red life
  recovers on the bench only, the CPU tags, and after a KO the incoming character's theme plays. About 60 readers
  in the executable (HUD `0x80054110`, rounds needed `0x800558ec`, round and match result `0x80056108`..,
  timer `0x80057ac0`, meter gain doubled when 1 at `0x80047d0c`, life-bar scale `0x80062058`) and in the code of
  11 characters, which is why one switch rather than a set of branch patches keeps everything consistent.
- `0x800250ac` menu mode: 0 BATTLE, 1 VERSUS, 2 TRAINING, 3 CROSS OVER, 5 HERO BATTLE. `0x8002504c` menu cursor.
- `0x80070a91` human-player bits (1 P1, 2 P2, 3 both, 0 = attract demo). `0x800707c4` arcade stage (7 = boss).
- `0x80070778` match structure: `+0` phase (8 fight, 10 K.O., 12 win pose, 14 PERFECT and bonus tally, 16, 18
  end), `+1` round, `+2` / `+3` wins, `+5` result, `+6` phase timer. `0x800707db` rounds needed.
- `0x800250c0` reduced-partner mask (a bit per character; cleared by the loader, set per cut-down partner).
- Default key configuration `0x8002477c` (L2, R2, L1, R1, triangle, circle, cross, square) = 3K, HK, 3P, HP, MP,
  MK, LK, LP: already the modern layout on the stock disc.

## Scenes

- Scene variable `0x80070a94`, dispatched through `jalr` at `0x800515d0` from the table `0x8006ae64` (scene / 4):
  4 map / select, 8 battle, 12 after the match (`0x800581a0`), 16 continue, 28 ending.
- Battle-scene init `0x800516c0`: battle loader call at `0x80051738`, then `0x80064e9c` (`0x80051754`), HUD and
  match init `0x800558ac`, object init `0x80039ab4`.
- Scene 12: when `0x80025070` is 0 (a win) it loads the win-quote overlay and portrait, then scene 4's map overlay
  picks the next opponent and stage. When it is not 0 the game takes its own short path: scene 12 skips the quote
  and scene 4 (`0x8004e81c` → `0x8004e8a8`) picks the next opponent and stage without the map and goes straight
  to the battle load. The START shortcut uses that path.

## Battle loader

`0x8002ac98`: builds the list of four characters from `0x800707ea`, removes duplicates (`0x8002abc8`), then per
slot: main → `0x8002a564(char, slot)` full load; partner → `0x8002a6d0(char, slot)` cut-down load and its bit in
`0x800250c0`. A slot whose character already matches the cache `0x80070538` is skipped. Same structure as the X-Men
vs. Street Fighter loader. In a fight the stage background starts at `0x800947bc`, then the shared effect sprites
(`SP_EFF0/1/2`), then the characters from `0x800bbfe4` up to about `0x801fd000`.

## Frame

| Address | Role |
|---|---|
| `0x80028ee4` → `0x80020b54` | main loop, one iteration per logic frame |
| `0x80028dbc` → `0x80028fb8` | mode dispatch and battle frame (logic and background) |
| `0x80048e1c` | sprite list (layers, extra list, per player) |
| `0x8008113c` | per-object sprite draw |
| `0x800828c4` | sprite frame build: parts loop, arena, decode, upload |
| `0x80081aa8` | quad builder per sprite part |
| `0x80082d9c` / `0x80083034` | part header / tile header parsers |
| `0x80083838` / `0x80083a2c` | sprite arena allocate / flush |
| `0x80083b3c`, `0x80084ab8` | decode wrappers; the game already decodes ahead from the list at `0x8008555c` |
| `0x8001bd68` | tile decoder (byte RLE, the same code as X-Men vs. Street Fighter's `0x8001b5b0`) |
| `0x80010e90` / `0x80010be4` / `0x80013798` | LoadImage / DrawSync / VSync |
| `0x800208c8` | present: DrawSync, VSync, flip |
| `0x80064b08`, `0x80064b8c`, `0x80064c10` | background layers |

## Sprites (`.DSP`)

```
+0  u32 kind   6: tile table of u32 words (every MSHvSF file)
               7: multi-set header (SP_EFF0/1, SP_SEL0)
+4  u32 off[4] section offsets (off[0] = 0x14)
sec0  pixels: one byte-RLE stream per tile
sec1  frames: u16 part count, 4 header bytes, then the part records (6 to 8 bytes)
sec2  tile table: bits 0-21 offset in sec0, 23 flag, 24-27 bytes / 8 - 1, 28-31 rows / 16 - 1
sec3  animation scripts
```

Part record: byte 0 flags (0x20 horizontal flip, 0x40 vertical flip, 0x80 same tile as the previous part),
bytes 1-2 tile (12 bits) and the x / y coordinate modes, byte 3 VRAM cell, then x and y. RLE control byte `c`:
if `c & 0xf0`, `(c >> 4) + 1` bytes of `(c & 15) * 0x11`, otherwise `(c & 15) + 1` literal bytes.

Decoder ABI (`0x8001bd68`, replaced in place by the patch): `dec(a0 = src, a1 = dst, a2 = bytes)`, where `src` is
the tile's stream inside any loaded `.DSP`. The table of each loaded file's pixel section is at `0x80087d40`
(16 × u32). The stock decoder may write up to 15 bytes past the tile. It uses only caller-saved registers, no
stack. The game uses scratchpad `0x1f800000-0x1f8000ff` only.

## Sound

- Bank upload `0x8007ae24(bank, src, size)`. A `.SE` file holds a u16 count, 18 zero bytes, then 20-byte entries
  from `+0x14` and the samples after them. Entry: `+0` id, `+2` volume, `+4` SPU offset / 8, `+6` / `+8` ADSR,
  `+0xe` note, `+0xf` sample note, `+0x10` priority, `+0x11` bank.
- Entries table `0x8007d330` (190 slots), id table `0x8007e220[id]` (the last bank loaded wins). Sample upload
  `0x8007b1ec`, unload `0x8007b06c(bank)`, play `0x8007a920(id, …)`.
- SPU RAM in a fight: common bank `0x01010-0x315d0`; the four character banks `0x315d0-0x67ff0` (stock: two
  full banks and two helper banks); sprite pixel stashes below `0x70800`; stage effect stash `0x70800-0x7a410`.
- Win-quote voices: ids from 0x600 (table `0x8006f6bc`).
- XA music: driver `0x8007c380(cmd, track)`, theme per character `0x8007d1a0[char]`, play `0x8007c084`.

## HUD, CPU and Cross Over

With the mode flag at 0 the HUD (four bars, the portrait following the point character), the CPU's tag logic,
Variable Counter (block, back / down-back / down + HP+HK, 1 level) and Variable Combination (QCF + HP+HK,
2 levels) are the game's own CROSS OVER code. The patch does not change them, so they were not mapped further.

## Secret characters and the select screen

- Character ids used here: 0x00 Apocalypse, 0x13 Cyber-Akuma (team word 0x26), 0x14 Mech-Zangief, 0x15 Dark
  Sakura, 0x16 Shadow, 0x17 U.S. Agent, 0x18 Mephisto, 0x19 Armored Spider-Man.
- Cyber-Akuma and Apocalypse are playable solo in the stock game: the select screen writes the same id into both
  team slots and skips the partner pick. Object init sets `1 << char` in `+0x2a0`; round init (`0x80039c0c`) gives
  such a partner life 0, so it is a dead dummy that cannot tag, assist or join a team super, and the main's KO ends
  the match. The arcade boss works the same way.
- The stock code for them (SELECT × 5 on Akuma for Cyber-Akuma, × 6 for Apocalypse) only counts when the save
  flag `0x80025076` has bit 1 / bit 0 set. The six other secrets (hold SELECT while confirming Blackheart, Hulk,
  Dhalsim, Bison, Omega Red or Spider-Man) are not gated.
- The select screen runs from `SEL.ARC` (read to `0x800947d4` by `0x8002b338`: a 0x2c-byte header, then the
  select code at `0x80094800`). `SELECT.BIN` holds the same bytes; the patch writes both.
- OPTION "SHORT CUT" (`0x80025070`) replaces the grid with a text list in the executable (input reader
  `0x8004f64c`, pick `0x8004fa60`, list positions from `0x8006abf4`), with the same codes and checks.
- TRAINING in stock gives the dummy one pick and copies it into the partner slot (a cut-down clone). The two
  branches that do that are `0x80096e98` in the select overlay and `0x8004ffd4` in the executable's SHORT CUT
  pick.

## Menus, options and input

- The main menu is loaded from `OPE.ARC` entry 0 (offset 0x34). `OPDEMO.BIN` is an identical copy the game does
  not use for the menu; patches have to go into `OPE.ARC`.
- Menu routine `0x80099404`, text table `0x800b5e3c`, drawn entries `0x800994b8`, cursor `0x8002504c`, START state
  table `0x800b6260`. Mode 3 (CROSS OVER) is set only by the handler `0x80099e2c`. Text print
  `0x80022e20(string, x << 16 | y, attributes)`; the menu's ON / OFF strings are at `0x80094b88` / `0x80094b8c`.
- The memory card saves the option block `0x8002506c-0x80025075` (plus the unlock flag `0x80025076`).
- Pads after the game's read: `0x80027d60` (P1) / `0x80027d62` (P2). Pad update `0x80023b88`, disconnected-pad
  mask `0x80023b54` (a missing pad on port 2 auto-pauses the fight).

## Code space

- The executable has large zero areas that are character and stage memory at run time (`0x80094801` + 0x277ff,
  `0x800bc001` + 0x33fff, `0x800f18e2` + 0xdb91e). Code placed there in the file must copy itself out at boot
  before the game's entry runs.
- Statically unreferenced code is not always dead: stage overlays (`BG*.ARC`) and character files call into the
  executable (for example `0x80083008`, `0x80083088`, `0x8005c820`, `0x8005c694`, `0x80040d58`), and some
  unreferenced routines run on the title screen, at boot or in Cross Over rounds (`0x80064f90`, `0x8007fd88`,
  `0x8007b4d4`). Any reuse needs a scan of every code file on the disc (`*.A0`, `*.BIN`, `*.ARC`) and a run-time
  fill test.
- Kernel RAM below `0x80010000`: emulators leave it zero, but on a real PlayStation (SCPH-5500 with a PSIO) parts
  of `0x8000C000-0x8000EFFF` hold BIOS and loader data, and the PS2 / PS3 PS1 BIOS keeps its own tables at
  `0x8000A8D0-0x8000AD60` and `0x8000B1A0-0x8000B7A8`. The spans the patch uses there were proven free on real
  hardware, and the achievements loader checks the BIOS date and stays out on a PS2 or PS3.
- Scratchpad: the game uses `0x1f800000-0x1f8000ff` in a fight.
