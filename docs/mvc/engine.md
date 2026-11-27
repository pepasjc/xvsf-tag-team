# Engine reference

What the patch relies on in *Marvel vs. Capcom: Clash of Super Heroes* for the PlayStation, USA (SLUS-01059). RAM
addresses; the executable `SLUS_010.59` is loaded at `0x80010000` (entry `0x800106e0`). How the patch uses all this
is in [architecture.md](architecture.md); the other games' counterparts are
[docs/xvsf/engine.md](../xvsf/engine.md) and [docs/mshvsf/engine.md](../mshvsf/engine.md).

These are working notes, verified as far as the patch needed them; anything not listed here was not looked at.

## Disc

- All game data is in `DAT/`, read through the game's own file table at `0x800255e4` (8-byte entries: BCD MSF,
  size) by `0x80024800(index, dest)`, not through the ISO directory. Music is XA (37.8 kHz stereo).
- Per character:
  - `PLxx_10.A0` (483-566 KB), with three sections:
    - code and data, 65-119 KB; word 0 counts the init entries, then registration code;
    - the sprite file (`.DSP`), 360-486 KB;
    - a 10-16 KB table.
  - `PLxx_20.A0`: the player 2 copy. It differs only in the code section (682 pointer words, 434 `j` / `jal`, 209
    `lui` and 208 low halves; the slot distance is `0x9cd00`), so the pair gives an exact relocation table.
  - `PLxx_11.A0` / `PLxx_21.A0` (37-54 KB): the cut-down partner (a 25 KB stub code set, a small sprite file).
  - `CHRxx_0.SE`: the sound bank.
  - `SPVCxx_0.DSP`: the super cut-in portrait.
  - `DAxx_11` / `DAxx_21` and `SPCxx`: the special partner (assist) code, sprites and sounds.
- `.A0` files: u32 section count, then (offset, size) per section.

## Characters and objects

Character ids (the `xx` of `PLxx`; the team words hold id × 2):

| Id | Character | Id | Character | Id | Character |
|---|---|---|---|---|---|
| 0x01 | War Machine | 0x09 | Ryu | 0x11 | Onslaught |
| 0x02 | Captain America | 0x0a | Captain Commando | 0x12 | Red Venom |
| 0x03 | Hulk | 0x0b | Chun-Li | 0x13 | Orange Hulk |
| 0x04 | Wolverine | 0x0c | Jin | 0x14 | Gold War Machine |
| 0x05 | Gambit | 0x0d | Zangief | 0x15 | Shadow Lady |
| 0x06 | Venom | 0x0e | Strider | 0x16 | Lilith |
| 0x07 | Spider-Man | 0x0f | Morrigan | | |
| 0x08 | Roll | 0x10 | Mega Man | | |

- Team `0x8007b8aa`: 4 × s16 character id × 2 (P1 main, P1 partner, P2 main, P2 partner), written by the select
  screen and read by the loaders. Special partners `0x8007b8d8`: 2 × s16 assist id × 4.
- Character form bytes from `0x8007b8e4` (P1 main, P2 main, P1 partner, P2 partner): Ryu's style (Ryu, Ken,
  Akuma), 2 for Mech Zangief.
- Player objects, 0x408 bytes each (MSHvSF 0x3c0, XvSF 0x348): P1 main `0x8007be90`, P2 main `0x8007c2a0`,
  P1 partner `0x8007c6f0`, P2 partner `0x8007caf8`. Special partner objects: P1 `0x8007bb90`, P2 `0x8007bca8`
  (0x118 bytes). Fields used:

| Offset | Meaning |
|---|---|
| `+0x00` | active (drawn and updated) |
| `+0x02` | side |
| `+0x03` | human (1) / CPU (0): selects the input path |
| `+0x04` | state (2 = normal), sub-states at `+0x06` / `+0x08` / `+0x0a` |
| `+0x10` | x position |
| `+0x30`, `+0x34`, `+0x3a` | current animation record, next record, frames left |
| `+0x3c` | current frame-table entry (low half = the frame group's offset in section 1) |
| `+0x47` | facing (1 = right) |
| `+0x4e` | character id × 2 |
| `+0x60` | animation and sprite data base |
| `+0x98` | number of the last move started (kept after it ends) |
| `+0xa0` | what hit it last (a projectile, beam or special partner object) |
| `+0xc8` | current move (0x40 = tag in / out) |
| `+0xd8` | opponent object |
| `+0xe6`, `+0xe8` | input bits |
| `+0x138` | hit counter of the current combo |
| `+0x187` | team-move participant (blocks the tag while set) |
| `+0x28a` | tag lock timer (0x3c after a tag-in) |
| `+0x294` | life (full = 0x90 = 144) |
| `+0x296` | super gauge within the level |
| `+0x298` | super level (0-3; the gauge is clamped to 0 at 3) |
| `+0x29e` | recoverable (red) life |
| `+0x2a2` | is the partner object |
| `+0x2a3` | benched (off-screen team member) |
| `+0x2a4` | other team member's character id × 2 |
| `+0x2a8` | partner object |
| `+0x2d8` | score (P1 at `0x8007c168`, P2 at `0x8007c578`) |

- Unlike X-Men vs. Street Fighter, a tag does not exchange the objects: the point character's object goes
  inactive (`+0 = 0`, `+0x2a3 = 1`) and the partner's becomes active. Main and partner objects keep their
  characters for the whole fight.
- Input bits (`+0xe6` / `+0xe8`, and the pads after the game's read at `0x80085040` + side × 2): right 1, left 2,
  down 4, up 8, LP 0x10, MP 0x20, HP 0x40, LK 0x100, MK 0x200, HK 0x400. HP + HK = 0x440. Default layout: square
  LP, triangle MP, R1 HP, cross LK, circle MK, R2 HK, so R1 + R2 tags.

## Modes and the tag switch

- Mode `0x8007b740`: 0 BATTLE (arcade), 1 VERSUS, 2 CROSS OVER. Main-menu cursor `0x8007b6f4`.
- Versus flag `0x8007b75d`: 1 in BATTLE and VERSUS, 0 in CROSS OVER; 114 readers in the executable. With 0 the
  engine runs the arcade's tag rules: tag with HP + HK, four life bars, KO hand-over, one round, team life decides,
  only the benched character recovers red life, the CPU tags, meter gain not doubled, no hyper chaining, limited
  special-partner stock.
- Human players `0x8007bdc9`: 1 P1, 2 P2, 3 both, 0 = the attract demo.
- Battle structure `0x8007b828`: `+0` phase (8 = fight, 0x0a and up = the match is decided), `+2` /
  `+3` rounds won by P1 / P2 (`0x8007b82a` / `0x8007b82b`), `+0xa0` / `+0xa4` / `+0xa8` / `+0xac` the four
  player objects. Round clock `0x8007b832`.
- Finish codes `0x8007b770` / `0x8007b772`: how P1 won its first / second round (P2: `0x8007b778`). Values the
  achievements use: 1 = KO on a blocking opponent, 7 = aerial rave, 8 = crossover combo; 6 is set by some hypers.
- Overkill: after a won fight the routine `0x8004ce30` lets the winning human press SELECT to bring the winner in
  again (`0x8007b84c` = 1, then 2 from the KO-phase input routine `0x80057ddc`).
- Main-loop counter `0x8007b74c` (one per logic frame), vblank count `0x8007b748`. Pause owner `0x8007b742`
  (0xff = not paused). Random numbers `0x8003bc88` (seed `0x8007b824`), advanced only by events, not every frame.
- TURBO SPEED option `0x8007b6fc`.

## Scenes

- Scene `0x8007bdcc`: 8 = battle, 12 = after the match (the loading screen), 0x1c = ending.
- At the start of scene 12 the handler `0x8002c960` draws the winner as a frozen sprite (`0x80090534`, 40 bytes per
  part) into a fixed buffer at `0x801fce00`.
- Arcade fight number `0x8007bdf2`, ending state `0x8007cf10`, continues `0x8007c16d`.

## Battle loader

- Versus / Arcade loader `0x8002b7a4`, Cross Over loader `0x8002bfe0` (keeps characters that are already in RAM).
  Per slot: main `0x8002aeec(char, slot)`, partner `0x8002b1ec(char, slot)` (the cut-down `_11` set), special
  partner `0x8002b384`. The list of four ids is de-duplicated first: a partner equal to the opposing main shares
  its data.
- Fixed slot bases, table `0x8006a6e4`: P1 main `0x800c5000`, P2 main `0x80161d00`, P1 partner `0x8014e500`, P2
  partner `0x801eb200`, special partners `0x80150d00` / `0x801eda00`. Character init entries: table
  `0x8006a70c`; special partner init: table `0x8006a7cc`.
- Sprite sets are registered with `0x800921a8` / `0x80091e74` / `0x80091d04` (pointers only).
- The GPU primitive pool is set up at `0x8002b498` (about 64 KB).
- In a Versus fight: stage background from about `0x8009dfcc`, the common effect sprites (`SP_EFF0`, 34 KB), then
  the four slots up to the stack at the top of RAM.

## Frame

| Address | Role |
|---|---|
| `0x80022f3c` | main frame (one logic frame) |
| `0x80022a0c` | present: DrawSync (`0x80022a18`), VSync, flip |
| `0x8002097c` | ordering table clear |
| `0x8004fb48` | per-frame player update (per-character hook table `0x8007a338`, state table `0x80071f8c`) |
| `0x8002dc68` | fighter input routine (CPU objects never reach the command matcher) |
| `0x8003da94` | CPU fighter AI |
| `0x8003c054` | animation step |
| `0x80047b60` | sprite draw by layers; per-object DrawOTag at `0x80011e58` |
| `0x8008c318` | sprite part decode (`jal 0x8001bd48` at `0x8008c434`) into the arena `0x80092c40`, then LoadImage |
| `0x8008f1f4` | part draw; decoded tiles stay in VRAM (bitmap `0x8009cf80`), so only a few decodes per frame |
| `0x8008f68c` | per-object frame-group reader (section 1) |
| `0x8008cca4`, `0x8008b538` | readers of the per-frame box data (section 3) |
| `0x8008a404` | stage background animation |
| `0x80020f10` | text print (8-pixel advance) |

Animation record (2-byte aligned for some characters): two u16 words; frame = `(w0 & 0xff) | (w1 & 0x7000) >> 4`,
duration = `w0 >> 8`, `w1 & 0x8000` = end (a u32 loop target follows).

## Sprites (`.DSP`)

```
+0  u32 kind   8: character sprites (5-byte tile entries); 6: effects, portraits, small sets (u32 tile words)
+4  u32 off[4] section offsets (off[0] = 0x14)
sec0  pixels: one nibble-RLE stream per tile (about 90 % of the file)
sec1  frame groups: u16 part count, 4 header bytes, then the part records (6 to 8 bytes)
sec2  tile table (kind 8): u24 offset in sec0, u8 width in bytes, u8 rows
sec3  per-frame box data, 11-39 KB per character
```

Part record parser `0x8008c6a8`, tile entry parsers `0x8008ca50` (u32) and `0x8008cac8` (5-byte entries; it keeps
22 bits of the offset).

The tile decoder `0x8001bd48` is the same nibble RLE as X-Men vs. Street Fighter's `0x8001b5b0`: a control byte
with a high nibble gives `hi + 1` bytes of `lo × 0x11`, otherwise `lo + 1` literal bytes. Decoder slots per loaded
file: table `0x80092b30`. Tile widths are any even byte count from 2 to 120 (up to 240 pixels).

Section 3 is reached through the main frame table and two inline stream formats in the animation data (absolute
jumps at `0x8003c3f4`, records relative to `+0x60` at `0x8003c340`).

## Team moves: crossover combo and Duo Team Attack

- Team supers go through the jump table `0x8006b988`, indexed by the object's `+8` / 2.
- State 2 (`0x80033298`) is the **Duo Team Attack**: QCB + HP + HK at super level 2 or more. It takes the levels
  (`0x8003ab30`), runs a timer in `+0x4a`, and brings the partner in to fight alongside. The stock game has it in
  Arcade, Versus and Cross Over (not Training), built for Cross Over, where the joining character is the other
  side's data.
- Super start `0x800305c4` (its only caller is `0x800332f8`). The Duo's two-portrait cut-in is spawned at
  `0x80030650` (`jal 0x80068b54`) and `0x8003066c` (`jal 0x80065d28`); its end is `0x80023a30`, called at
  `0x80023b48`.
- The cut-in background is parked in VRAM in compressed form at the battle load. When the cut-in starts
  (`0x80023910`, triggered by `0x800255d9` from `0x80023b00`) the game reads it back with StoreImage
  (`0x80044f44`), decodes it (`0x80045a80`) into the arena `0x80092c40` and loads it to VRAM (642, 258). The
  portraits come from the SPVC sets 14 and 15 (the two mains).
- The crossover combo (QCF + HP + HK) is the other team super.

## Tag and CPU

- Tag routine `0x80055fa8`, called from every character's neutral states; the input check `0x80055fb0` refuses in
  the air, with the partner at 0 life, from phase 0x0a on and while `+0x28a` runs. A human (`+3` = 1) needs HP + HK
  (`0x80057c8c(obj, 0x440)` at `0x80056088`); then the busy check `0x80034240`, then the tag move
  (`0x8003d04c(obj, 0x40)`).
- The CPU branch needs the AI's tag action (command 0x76, `0x8004085c`), which the PlayStation CPU almost never
  runs, and leaves at `0x80056080` anyway: the stock CPU does not tag in Versus or Arcade.
- Team controller `0x80031f88` (per side), tag flow `0x80031d08` / `0x80031efc` / `0x80031ea4`.

## Special partners (assists)

- Input `0x80056344`, per-side bits. The stock per assist matches the arcade's.
- The roulette on the select screen (`SEL01.ARC`) follows the arcade rules: a button press stops it on the
  highlighted partner, it stops by itself after 41-79 frames, and START plus a held button combination (LP 1, MP 2,
  HP 4, LK 8, MK 16, HK 32), read when the roulette wraps, picks partner N (21 = Shadow, 22 = Sentinel). The
  reader of that code is at `0x80198aec`.
- HUD portrait colours: `0x8006cc20` + 32 × the entry of the map `0x8006ed9c[assist]`.

## Select screen, stages and Onslaught

- The select code runs from `SEL01.ARC` (file table entry at `0x8002617c`).
- Stages 0-9 (`BGnn.ARC`), 9 = Onslaught's. Stage byte `0x8007bdd9`. VERSUS takes it from the VERSUS stage setting
  `0x8007b780`, copied by the select overlay at `0x8018f070`. Stage 8's sunset and night are palette fades driven by
  the round clock.
- The executable holds static pointer tables into stage data, and stage overlays call into the executable
  (`BG09.ARC` and `END.ARC` call `0x800222ac`-`0x80022564`).
- Playable Onslaught is in the stock game: a hidden cell (down from Wolverine, behind an unlock word read at
  `0x80190ce0`). The select screen then skips the partner pick (partner word 0x22, the same value Cross Over uses
  for "eliminated") and sets stage 9. His second form is triggered from his own code (the hit handler's KO clamp and
  a low-timer state). A time-over loss as Onslaught waits in phase 10 for the stage-9 death sequence (`0x8004bf54`).

## Menus, options and input

- The main menu is `OPDEMO.ARC`. Its text table is at `0x800b5bb4`, its START state table at `0x800b5bf8`; state 8 is
  a hidden EX OPTION screen. Option cursor `0x8007b6f5`. Menus ignore input for about 150 frames after the fade-in.
- Pause menu: START, then SELECT. Table `0x8006a668`, draw `0x80029f44`, input `0x8002a08c`. `0x8007b708` is the
  player-join mask and `0x8007b709` the pause cursor; the reset `0x8005b778` clears that block.
- SELECT is also the taunt: the pad mapper `0x80024934` sets the side's bit in `0x8007be49`, the move decoder reads
  it at `0x8005698c`; pose per character from `0x80071954`.
- Memory card save: a 0x500-byte file, data `0x100`-`0x4fb`, XOR checksum at `0x4fc`, written and checked by
  `OPDEMO.ARC` (`0x8009ec28` / `0x8009edb8`) and loaded at boot.
- The attract demo is CPU against CPU (human players 0) through the stock loaders. Its second intro is loaded
  over `0x80102e14`-`0x8010d5a0`.

## Sound

- `.SE` banks; play `0x80086fc8`, menu sound `0x80085a7c(0)`, SPU write `0x8001bc88` (transfer address word
  `0x8001e90c`), sound tick `0x80022f54`, VSync `0x8001e214`.
- In a fight the four characters' banks share SPU RAM with the common bank; each fighter's small sprite set (kind
  6) keeps its pixels in SPU RAM too. libspu waits for SPU transfers with a BIOS event fed by the DMA 4 interrupt.

## Code space

- The executable has zero areas that are character memory at run time (`0x80100000`-`0x80140000` and up); code
  placed there must copy itself out at boot.
- Statically unreferenced code is not always dead (stage overlays and the ending call into the executable); any
  reuse needs a scan of every code file on the disc and a run-time fill test.
- Kernel RAM below `0x80010000`: on a real PlayStation with a PSIO parts of `0x8000C000`-`0x8000EFFF` hold BIOS and
  loader data, and the PS2 / PS3 PS1 BIOS keeps its own tables at `0x8000A8D0`-`0x8000AD60` and
  `0x8000B1A0`-`0x8000B7A8`. The spans the patch uses there were proven free on real hardware.
- Scratchpad: the player sprite path runs with the stack pointer inside the scratchpad, so code hooked there must
  not use the stack.
