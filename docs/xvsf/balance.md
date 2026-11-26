# ARCADE BALANCE

A row in EX OPTIONS, **ARCADE BALANCE OFF / ON**, saved on the memory card with the game's other options (in 1.3
it was a line in OPTION MODE).
Default OFF.

- **OFF:** the PlayStation game exactly as before.
- **ON:** the two gameplay rules the port changed from the CPS2 arcade go back to the arcade's:
  1. **Super meter gain is halved.** The PlayStation doubles every meter gain (hit, whiff, block, being hit).
     With ON, a standing heavy punch that hits gives 16 meter units instead of 32 (144 units = one level), the
     same as the arcade.
  2. **No super chaining.** The PlayStation lets a super start while the character is still in a special move or
     another super once it has hit; for example, Gambit can chain three Royal Flushes and the opponent never
     recovers. The arcade refuses that: a super starts only from a free state or from a normal move. With ON the
     arcade rule applies. (Cancels from normal moves into specials and supers work as before.)

## How

The port still carries both rule sets. A "PS1 mode" flag (`0x8004278c`, always 1 on the PlayStation) selects
between the PlayStation and the arcade branch at about fifty places; most of them belong to the tag system, the
HUD and the match flow, which the tag hack already replaces. Two are gameplay rules: the meter add at
`0x80075144` and the move-start check at `0x8007d628`. With ARCADE BALANCE ON, those two take the arcade branch,
which is the port's own translation of the arcade code. Nothing else changes, and it costs no time per frame.

## What was compared

Measured side by side (the arcade in an emulator with the USA set at factory settings, the PlayStation hack in an
emulator, the same inputs):

- **The same on both:** the damage of normal moves, specials and the supers tested, red life and benched
  regeneration, throw and tag-in damage, chip damage, hit stun, dizzy, normal-move cancels, the meter cost of a
  super and the maximum level.
- **Changed by ARCADE BALANCE:** meter gain and super chaining (above).
- **Already arcade since 1.0:** the round timer runs at the arcade's factory speed.
- **Left as an option:** game speed. The arcade's USA factory setting equals the PlayStation's Turbo Speed 2;
  the hack keeps the retail default (Turbo off).
- **Small differences not changed:** the hit count of a few multi-hit supers, and the down time after some
  supers.

The achievements count with ARCADE BALANCE on or off.
