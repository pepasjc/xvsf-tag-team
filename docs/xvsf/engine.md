# Engine reference

What the patch relies on in *X-Men vs. Street Fighter* for the PlayStation, USA (SLUS-00627). RAM
addresses; the executable `SLUS_006.27` is loaded at `0x80010000` (file offset = address − 0x80010000 +
0x800). Overlays (`P/P4/OPDEMO.BIN`, `P/P4/SELECT.BIN`, stages) are loaded at `0x80098000`.

These are working notes, verified as far as the patch needed them; anything not listed here was not
looked at.

## Characters and objects

- Character ids (value = character × 2): `0x800423b2` P1 main, `0x800423b4` P1 partner, `0x800423b6`
  P2 main, `0x800423b8` P2 partner. 0 Wolverine, 1 Cyclops, 8 Apocalypse (boss), 9 Ryu, … 18 the last.
- Player objects, 0x348 bytes each: P1 `0x80042a10`, P2 `0x80042d58`, P1 partner `0x80043178`, P2
  partner `0x800434b8`. Fields used:

| Offset | Meaning |
|---|---|
| `+0x00` | active |
| `+0x02` | side |
| `+0x04`..`+0x0a` | state words (main state 2 = normal, `+0x06` sub-state 0 = neutral) |
| `+0x54` | character id × 2 |
| `+0x6c` | sprite set |
| `+0x74` | "assist only": the cut-down partner; blocks the per-character command parser (no specials) |
| `+0xad` | special-state id |
| `+0xcc`, `+0xce`, `+0xdc` | input history, newest first |
| `+0xe2` | team move requested by the CPU |
| `+0x224` | life (full = 0x90) |
| `+0x22a` | alternate colour flag |
| `+0x22c` | recoverable (red) life |
| `+0x22e` | regeneration timer |
| `+0x230` | "swapped": the benched character's object |
| `+0x231` | is a partner object (flag) |
| `+0x234` | the other object of the side |
| `+0x238` | colour row index |
| `+0x247` | regeneration delay |
| `+0x25e` | per-frame team request (2, 4 tag, 6 counter, 8/10) |
| `+0x262` | lockout timer after a tag |

- Per-frame player update `0x8007693c`: clears `+0x25e`, dispatches the sub-state through the table
  `0x80094930` (`jalr` at `0x80076dd0`, the tag hook's place), then dispatches `+0x25e` through
  `0x80094940`: 2 → `0x8006e3c0`, 4 → `0x8006e3f0` (tag), 6 → `0x8006e9a0` (counter), 8/10 →
  `0x8006e8c8`.
- Swap `0x8006b248`: exchanges `+0x230`, `+0x74`, `+0x75`, the life fields and `+0x40` between the main
  and the partner object of a side, then re-initialises both. Called by the three team requests and by
  the KO replacement (`0x8008e0a4`).

## Mode flag and tag system

- `0x8004278c` is the PlayStation mode flag: 1 in every mode the menus offer, set once at `0x80031a84`,
  48 readers. Where it is 0 the arcade's tag rules apply. The patch changes individual readers, not the
  flag.
- Arcade tag: team move `0x2a` (`0x8003252c(obj, 0x2a)`) with `+0xe2` = 0x14 → character code → leave
  state `0x8007bc70` → request 4 (swap, jump-in attack, palettes). The arcade input routine `0x8007cd94`
  returns early for a human player in PlayStation mode.
- KO: the hit handler `0x80071af0` sends a character with 0 life to KO or, when the partner has life, to
  the leave state; the partner replaces it.
- Life regeneration `0x80075414`: in PlayStation mode both active characters heal (`0x8007537c`); in
  arcade mode only the benched objects (`0x80075494`). The life bar routine `0x800804e0` shows the
  regeneration look (bar animation, sparkle at the tip, `0x8003c460`) by the same rule (test at
  `0x80080584`). On a swap the incoming character's red life is cleared only in arcade mode (`0x8006b340`).
- Round init `0x8006b0c0` zeroes the partners' life in PlayStation mode.
- The reduced-set mask `0x800421bc` has a bit per partner loaded as the cut-down set.
- End of a team move (team super): resolver `0x8006e59c`; its mode-flag test at `0x8006e6f0` picks the
  PlayStation branch (the partner leaves again) or the arcade branch (the partner stays on point, with a
  swap).
- Variable counter `0x8007cc4c`; its PlayStation-mode path at `0x8007cc9c` reads `0x80042387`. The counter
  prep `0x8006d50c` sets the side's bit in `0x80042387` ("assist is out"). The counter move's effect object
  (handler `0x8008ded4`) swaps the owner back in PlayStation mode (mode test `0x8008dfe8`; swap-back
  `0x8008e07c`: `0x8008d868`, swap `0x8006b248`, `0x8006ee34`), and only that swap-back clears the bit.
- Team-move veto `0x8006f84c(obj)`: nonzero while the engine forbids a tag or team move (guard stun,
  opponent in a throw, ...). In PlayStation mode (mode test at `0x8006f850`) it also reports "blocked" while
  the side's `0x80042387` bit is set. Called by the command parser, the tag and counter routines.
- The arcade's last fight (after the boss) is the point character against its own partner, one per side:
  the arcade sets both partner slots to the boss id with 0 life. The port mirrors the team instead (P1
  main = P1 partner, P2 main = P2 partner, all four with full life); in arcade mode (`0x8004218c` = 1)
  that is the only fight in which both sides are mirrored.

## HUD

- Display values of the four bars, written every frame from `0x80033fbc`: `0x80042388` (P1 slot 0),
  `0x8004238a` (P1 slot 1), `0x8004238c` (P2 slot 0), `0x8004238e` (P2 slot 1).
- Yellow bars `0x8008096c` → `0x800804e0(state, obj, x, y, value, slot)`; the partner slots only when the
  mode flag is 0. A slot whose object has `+0x230` set is drawn thin.
- Red bars `0x80080d08` (all four slots, `0x80080b14`); bar frames `0x80080eec`.

## Match

- Match struct `0x80042348`: `+0` phase (table `0x80095098`; 8 = fight), `+1` round, `+2`/`+3` rounds
  won, `+4` round winner, `+5` match result, `+8` timer seconds, `+0xd` time-over flag.
- The fight phase decides by team total (main + partner life on each side). Mode `0x8004218c`: 1
  arcade, 2 versus, 3 training, 4 survival.
- Match init `0x80081c6c` sets the rounds needed; the match result `0x800828b4` has the arcade rule at
  `0x800828f0` and the best-of-N rule at `0x80082928`.
- Timer reload `0x800837c4`: 100 frames per count in PlayStation mode; the arcade's factory setting is
  110.

## Music

- XA driver `0x8004e490(cmd, track)`; stop `0x8004f1c8`; state `0x80053dc2` playing, `0x80053dc4` track.
  Track → file and XA channel through the pairs at `0x80050638 + 2 × track`.
- Themes per character: `0x80050378[char]`.
- KO with a living partner (`0x80071be4`, `0x80072a04`): fade, then, only with the mode flag 0, the
  incoming character's theme.

## CPU

- The CPU's script interpreter `0x80087858` orders team moves through `+0xe2` with `+0x27f` = −1
  ("command pending").
- Difficulty: the option `0x800421a4` (0..7) picks a row of the rank-cap table `0x80090d6c`; the CPU
  reads its rank at `0x80042a02` (0..31). The arcade has the same table.

## Files and loading

- File table `0x8003d91c`: 8 bytes per file, 3 bytes BCD minute/second/frame and a 32-bit size. Every
  load goes through it, not the ISO directory.
- `LOADFILE(index, destination)` `0x8002de3c`: stops the audio stream, reads whole sectors, returns the
  size.
- Sprite loader `0x80053f78(set, offset)`; set loader `0x80054054`. Section pointer tables of the sprite
  sets: `0x8006a358`, `0x8005ce80`, `0x8005c830`, `0x80069de0`.
- Battle loader: effects file at `0x8002b154`, pool init at `0x8002b1ac`.
- Sprite file: four sections, described in `tools/nsp.py`. RLE tile decoder entry `0x8001b5b0`.
- Shared-slot tables: one per sprite set, pointers at `0x8005c65c + 4 × set`; an entry is
  `{u16 users, u16 -, u32 VRAM block}`, the table ends with users = 0xffff.
- Character code registers about 30 per-character tables in its init routine (table of inits
  `0x8003d83c`). The overlays exist twice on the disc, linked at `0x800d1000` (`P/P0`) and `0x80152000`
  (`P/P2`).
- Palettes: `0x80042258[char]` points into the character's data (3 colour rows, alternate set at
  `+0x60`); `0x8002e018(obj)` uploads the rows of an object's side.

## Sprite pipeline

The 1.1 speed work rewrote most of this; the addresses and interfaces stay.

- Main loop: layer dispatch `0x80028868`, draw and present `0x80028b58` (its `DrawSync(0)` at `0x80028a44`
  waits for the GPU to finish the previous frame), sprite-list dispatcher `0x8002e6bc` with four list
  walkers. One-shot dispatcher: byte `0x8004218f` − 1 indexes the jump table `0x800280e8`.
- Logic frame counter `0x800421b8`, vblank counter `0x800421b4`, random number state `0x80042308`. Stage id
  `0x80042781` (the battle overlay is `P/P4/STAGE<id hex>.BIN`).
- Per-object sprite draw `0x80059e60(obj)`: reads the frame record (section 3) and layout, then either
  rebuilds the quads only (same frame as last time; then it may pre-decode the next frame), or frees and
  allocates the object's VRAM rectangle (first fit `0x8005883c`, pages at x = 384 + 64 i, y = 256; shared
  slots `0x8005c258` / `0x8005c4f8`) and runs one of three upload loops: `0x8005935c` (everything
  pre-decoded), `0x80059564` (partly), `0x80059930` (decode and upload part by part).
- Its globals live in the scratchpad (`*0x8006a340` = `0x1f800000`), with a small scratch stack at
  `+0x70`. The game uses `0x1f800000`–`0x1f800207`; the 1.1 decoders use `0x1f800280`–`0x1f8003ff` within
  one call.
- Decoded tiles go to the arena (`*0x80060af0` = `0x800620e0`, 31,088 bytes, size at `0x8005d95a`) before
  `LoadImage` sends them to VRAM by DMA. Arena blocks: 70 structs of 16 bytes at `0x80069ee0` (sorted list
  head `0x8006a34c`, tail `0x80069a80`, free pool `0x8006a344`); allocator `0x80058d04` (first fit); on
  failure the callers `DrawSync(1)`, flush everything (`0x800590c4`) and retry. An uploaded block stays
  allocated until the end-of-frame sweep `0x80058f84`, because the DMA reads it later. In supers the flushes
  come from running out of the 70 structs, not out of bytes.
- Quad builder `0x80056340` (per sprite part), frame-record parsers `0x80057be4` (section 0) and
  `0x80057f48` (section 1). The animation script step is `0x80030868` (object `+0x34`/`+0x38`/`+0x44`/`+0x48`).
- Draw list insert `0x800303f0`; command matcher of the move parser `0x8007d100` (about 18 calls per frame).
- libgpu: `LoadImage` `0x80016718`, `StoreImage` `0x8001677c`, `DrawSync` `0x80016454`, `DrawOTag`
  `0x80016a54`, `TermPrim` `0x80015a68`; queue `_addque` `0x80018510`, `_exeque` `0x800187f0`, timeout check
  `0x80018db4`; queue state `0x80022530`–`0x8002263f`, ring `0x80025f80`–`0x8002773f`.
- BIOS A0 memory routines are called through stubs at `0x80019290` (`bcopy`, `bzero`, `memcpy`, `memset`,
  16 bytes each). The attract demo clears a GPU primitive buffer with `bzero(0x3000)` while draws into it
  are still queued, and relies on the slow BIOS loop.
- Stage background layers are compiled per stage (`STAGEn.BIN`): a handful of templates that build a
  25 × 16 map of 16 × 16 `SPRT` primitives, plus one-off variants.

## Menus and pad

- Main menu text routine `0x80098728` (`OPDEMO.BIN`), ends with `jr ra` at `0x800987b8`.
- Option screen (`OPDEMO.BIN`): structure `0x80042180`, cursor `+0x13` (0..11), values from `+0x17`;
  label loop `0x80098bdc` (names at `0x800aceec`), cursor wrap `0x8009927c`; text `0x8002d79c(text, x,
  y, step, colour, 1)` (colour 0x30 highlighted, 0x33 normal).
- Pad: `0x8002c8e0(port)` buttons held now, `0x8002c8f8(port)` held before; pad 1 raw at `0x800420d0`.
  The game copies the pad state from the BIOS buffers `0x80060aa0` / `0x80060ac8` to `0x80043984` /
  `0x80043986` through `0x8002c72c`.
  Default key table `0x8003d8f8` (eight action masks in pad-bit order L2 R2 L1 R1 △ ○ × □; LP 0x10,
  MP 0x20, HP 0x40, LK 0x100, MK 0x200, HK 0x400).

## Code space

Executable ranges the patch uses were verified dead by filling them with `break` and playing (boot,
menus, fights). `CdSearchFile` (`0x80014698`–`0x80015024`) is live and must not be touched. The 1.1
rewrites free more: the quad builder and parsers leave `0x80055c34`–`0x80055ebc`, `0x80056b94`–`0x800577c8`,
`0x80057d7c`–`0x80057f48` and `0x80057fbc`–`0x80058000` unreferenced; `0x8006b6a4`–`0x8006b71c` and
`0x8006cdec`–`0x8006ce74` are statically unreferenced and hold part of the command matcher.

## Notes

- The game is timing-sensitive: any change in code speed changes how a fight plays out from that frame
  on, so two builds cannot be compared by frame hashes. Compare state, and look at screenshots.
- The game reads registers that library calls leave behind: the score code `0x80075550` ORs a leftover
  `a2` from a libgpu call into player byte `+0x117` (the leftover depends on the GPU queue state, so on
  timing). Rewritten library code must leave the same values in every caller-saved register.
- Locking every logic frame to five vblanks (`VSync(5)`) makes two builds comparable frame by frame. The
  input a frame sees depends on when its pad read lands relative to the BIOS's update: change the pad
  from the fourth vblank of the previous frame, not on the vblank where the frame counter changes.
