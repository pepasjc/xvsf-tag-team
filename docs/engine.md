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

## Menus and pad

- Main menu text routine `0x80098728` (`OPDEMO.BIN`), ends with `jr ra` at `0x800987b8`.
- Option screen (`OPDEMO.BIN`): structure `0x80042180`, cursor `+0x13` (0..11), values from `+0x17`;
  label loop `0x80098bdc` (names at `0x800aceec`), cursor wrap `0x8009927c`; text `0x8002d79c(text, x,
  y, step, colour, 1)` (colour 0x30 highlighted, 0x33 normal).
- Pad: `0x8002c8e0(port)` buttons held now, `0x8002c8f8(port)` held before; pad 1 raw at `0x800420d0`.
  Default key table `0x8003d8f8` (eight action masks in pad-bit order L2 R2 L1 R1 △ ○ × □; LP 0x10,
  MP 0x20, HP 0x40, LK 0x100, MK 0x200, HK 0x400).

## Code space

Executable ranges the patch uses were verified dead by filling them with `break` and playing (boot,
menus, fights). `CdSearchFile` (`0x80014698`–`0x80015024`) is live and must not be touched.

## Notes

- The game is timing-sensitive: any change in code speed changes how a fight plays out from that frame
  on, so two builds cannot be compared by frame hashes. Compare state, and look at screenshots.
