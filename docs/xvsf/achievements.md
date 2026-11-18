# X-Men vs. Street Fighter Tag Hack: achievements

Built into the 1.3 image: an **ACHIEVEMENTS** page in the main menu (above OPTION MODE), a popup when one
unlocks, and progress saved in its own memory card file. Nothing is sent anywhere; the set runs on the console.

RetroAchievements has no set for X-Men vs. Street Fighter on the PlayStation, so this set was written for the
tag hack: 28 achievements, 205 points.

| # | Title | Points | Goal |
|---|---|---|---|
| 1 | Children of the Atom | 10 | Beat Apocalypse in Arcade mode |
| 2 | Berserker Barrage | 5 | Arcade clear with Wolverine |
| 3 | Optic Victory | 5 | Arcade clear with Cyclops |
| 4 | Weather the Storm | 5 | Arcade clear with Storm |
| 5 | Southern Belle Brawl | 5 | Arcade clear with Rogue |
| 6 | Raise the Stakes | 5 | Arcade clear with Gambit |
| 7 | Feral Instinct | 5 | Arcade clear with Sabretooth |
| 8 | Unstoppable | 5 | Arcade clear with Juggernaut |
| 9 | Master of Magnetism | 5 | Arcade clear with Magneto |
| 10 | Heart of Battle | 5 | Arcade clear with Ryu |
| 11 | Shoryuken Showboat | 5 | Arcade clear with Ken |
| 12 | Spinning Bird Champion | 5 | Arcade clear with Chun-Li |
| 13 | Yoga Inferno | 5 | Arcade clear with Dhalsim |
| 14 | Red Cyclone | 5 | Arcade clear with Zangief |
| 15 | Psycho Crusher | 5 | Arcade clear with M. Bison |
| 16 | Raging Demon | 5 | Arcade clear with Akuma |
| 17 | Sonic Boom Salute | 5 | Arcade clear with Charlie |
| 18 | Delta Red Mission | 5 | Arcade clear with Cammy |
| 19 | Flawless Crossover | 25 | Arcade clear, no fight lost |
| 20 | Apocalypse Averted | 10 | Beat Apocalypse, both standing |
| 21 | Dream Team | 10 | Arcade clear: X-Man + SF team |
| 22 | Tag, You're It | 5 | KO a foe with your 2nd pick |
| 23 | Perfect Partners | 10 | Win, both at full life |
| 24 | Last One Standing | 5 | Win after losing your 1st pick |
| 25 | Combo Rookie | 5 | 10-hit combo |
| 26 | Combo Expert | 10 | 20-hit combo |
| 27 | Infinite Combo | 25 | 35-hit combo |
| 28 | Rival Showdown | 5 | Beat a player in Versus mode |

- "Arcade clear with ..." counts when that character is on your team, as first or second pick.
- Combos count the real hit counter of the character on point.
- Achievements count with ARCADE BALANCE on or off.

## Memory card

- Progress goes into its own save file on a memory card (slot 1 or 2). The page's first line shows where it is saved, or "NO MEMORY CARD" / "MEMORY CARD FULL".
- Without a usable card the main menu shows "ACHIEVEMENTS NOT SAVED" once, and popups read "UNLOCKED (NOT SAVED)".
  The unlocks wait: the menu checks the card again every few seconds and saves them as soon as it can.

## When they switch off

The runtime lives in kernel RAM that the PlayStation BIOS leaves unused. At boot it checks that this memory stays
untouched; if anything else writes there (a PS2 or PS3 in PS1 mode, some other loaders), the achievements stay off
and the game runs normally. ARCADE BALANCE and the START shortcut do not depend on them.

The command-line builder can leave them out: `--no-achievements` (see [BUILDING.md](../../BUILDING.md)).
