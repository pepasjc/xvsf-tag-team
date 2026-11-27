# ARCADE BALANCE

A row in EX OPTIONS, **ARCADE BALANCE OFF / ON**, saved on the memory card with the game's other options.
Default OFF.

- **OFF:** the PlayStation game exactly as before.
- **ON:** the two gameplay rules the port gets wrong compared with the CPS2 arcade work as in the arcade:
  1. **Meter gain on block.** When a move is blocked, the attacker's meter gain comes from the move's hit data,
     halved, as in the arcade. The PlayStation reads the wrong byte and swaps two of the cases, so some moves give
     far too much: War Machine's blocked QCF + HP (eight hits) gives 69 meter units instead of the arcade's 13
     (144 units = one level), Wolverine's QCF + HP 8 + 4 instead of 5 + 1.
  2. **Red-life minimum.** Every hit takes max(1, damage × 24 / 32) off the recoverable (red) part of the life,
     the arcade's rule. The PlayStation has no minimum, so chip damage and small hits stay fully recoverable:
     after War Machine's blocked QCF + KK the PlayStation leaves 12 points of red life, the arcade none.
  3. The Onslaught boss fight, which the game still loads its own way, gets the rules every tag battle already
     uses (below): normal meter gain, no hyper chaining, no regeneration of the point character.

## How

The port carries both rule sets. The Versus flag (`0x8007b75d`, read at 114 places in the executable) selects the
PlayStation's Arcade / Versus rules (1) or the Cross Over rules (0), and the Cross Over branch is the arcade's: meter
gain not doubled, no hyper chaining, only the benched character regenerates, limited assists. The tag hack runs
every tag battle with the flag at 0, so those rules are already the arcade's with ARCADE BALANCE OFF.

What is left are unconditional port changes:

- the block meter grant at `0x8003a8c0` (8 instructions differ from the arcade's logic);
- the red-life update at `0x8003ac28` (7 instructions);
- nine readers of the Versus flag in the gameplay code, for the battles the game loads itself (the Onslaught boss
  fight).

A small hook in the select screen's code runs at every character pick and writes either the arcade or the stock
words, so the setting is in place before any battle and holds for the whole Arcade run. It costs nothing per
frame.

## What was compared

Measured side by side (the arcade in an emulator with the USA set at factory settings, the PlayStation hack in an
emulator, both sides human, 27 moves in 6 match-ups, hit and block, game speed matched to one logic frame per
video frame):

- **The same on both:** the attack data of every move of all 21 characters, damage levels, combo and hyper
  proration, defence per character, the victim's meter gain, assist stocks, the CPU rank tables (the PlayStation's
  default 2 stars = the arcade's NORMAL), 144 life for every character, hit and block stun, startup and recovery,
  meter gain on hit and whiff, the cost of hypers and team moves (1 / 2 / 3 levels), bench regeneration (+1 every
  51 frames), the round timer (110 logic frames per count), movement, guard push, throw tech window, air block,
  juggle limits.
- **Changed by ARCADE BALANCE:** meter gain on block and the red-life minimum (above).
- **Left as an option:** game speed. The arcade's factory setting equals the PlayStation's TURBO SPEED 2 stars;
  the hack keeps the retail default.
- **Not data:** the arcade's random number generator also runs on idle frames, the PlayStation's only on events,
  so the damage of some hits differs by a point or two from fight to fight; this was left alone. A few inputs
  start a different move on each machine (command recognition), and the arcade reads input one frame later.

The achievements count with ARCADE BALANCE on or off.
