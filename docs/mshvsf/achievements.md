# Marvel Super Heroes vs. Street Fighter Tag Hack: achievements

Built into the 1.0 image: an **ACHIEVEMENTS** page in the main menu, a popup when one unlocks, and progress saved
in its own memory card file. Nothing is sent anywhere; the set runs on the console.

The set is adapted from the RetroAchievements set for this game
([game 16340](https://retroachievements.org/game/16340)), by **Lowsun**. Every achievement keeps its goal; the
conditions were rewritten for the tag hack (single-round fights, either member of your team counts, the game's real
hit counter for the combo achievements). 46 achievements, 420 points.

| # | Title | Points | Goal |
|---|---|---|---|
| 1 | Tag-Team Troublemaker | 5 | KO an opponent with your second character on point |
| 2 | Untouchable Force | 5 | Win a fight with both of your characters at full life (default or higher difficulty) |
| 3 | Lossless Multiversal Clear | 50 | Finish Arcade mode without losing a fight (default or higher difficulty) |
| 4 | Total Annihilation Pushed Back Another Day | 25 | Defeat Cyber-Akuma (default or higher difficulty) |
| 5 | Wanderer of the Hadouken | 10 | Finish Arcade mode with Ryu on your team (default or higher difficulty) |
| 6 | Blonde Ambition: Fire Edition | 10 | Finish Arcade mode with Ken on your team (default or higher difficulty) |
| 7 | Master of the Saikyo Struggle | 10 | Finish Arcade mode with Dan on your team (default or higher difficulty) |
| 8 | Kicking First, Questions Later | 10 | Finish Arcade mode with Chun-Li on your team (default or higher difficulty) |
| 9 | The Art of Zenmetsu | 10 | Finish Arcade mode with Akuma on your team (default or higher difficulty) |
| 10 | Honor Student of Street Fighting | 10 | Finish Arcade mode with Sakura on your team (default or higher difficulty) |
| 11 | Suplex the Earth | 10 | Finish Arcade mode with Zangief on your team (default or higher difficulty) |
| 12 | Psycho Power Paradise | 10 | Finish Arcade mode with M. Bison on your team (default or higher difficulty) |
| 13 | Yoga Around the World | 10 | Finish Arcade mode with Dhalsim on your team (default or higher difficulty) |
| 14 | Visor Violence | 10 | Finish Arcade mode with Cyclops on your team (default or higher difficulty) |
| 15 | Friendly Neighborhood Deconstructor | 10 | Finish Arcade mode with Spider-Man on your team (default or higher difficulty) |
| 16 | Stars, Stripes, and Smackdowns | 10 | Finish Arcade mode with Captain America on your team (default or higher difficulty) |
| 17 | Single-Eyed Superiority | 10 | Finish Arcade mode with Shuma-Gorath on your team (default or higher difficulty) |
| 18 | Man Made Me a World-Wide Weapon | 10 | Finish Arcade mode with Wolverine on your team (default or higher difficulty) |
| 19 | Rampage World Tour | 10 | Finish Arcade mode with Hulk on your team (default or higher difficulty) |
| 20 | Demonic Duties Fulfilled | 10 | Finish Arcade mode with Blackheart on your team (default or higher difficulty) |
| 21 | Cold War, Warm Blood | 10 | Finish Arcade mode with Omega Red on your team (default or higher difficulty) |
| 22 | My Journey Has No End, But 20 Will Suffice | 5 | Perform a 20-hit combo with Ryu |
| 23 | Flame Cascade Finale | 5 | Perform a 20-hit combo with Ken |
| 24 | Short Range Hadouken Hit Faster | 5 | Perform a 20-hit combo with Dan |
| 25 | Fastest Feet in the Multiverse | 5 | Perform a 20-hit combo with Chun-Li |
| 26 | Combo No Jutsu: Destruction Style | 5 | Perform a 20-hit combo with Akuma |
| 27 | After-School Beatdown Club | 5 | Perform a 12-hit combo with Sakura |
| 28 | Cyclone Compression Therapy | 5 | Perform a 12-hit combo with Zangief |
| 29 | Psycho Combo-nation | 5 | Perform a 12-hit combo with M. Bison |
| 30 | Average 12-Move Yoga Routine | 5 | Perform a 12-hit combo with Dhalsim |
| 31 | Optic Blast-tacular | 5 | Perform a 12-hit combo with Cyclops |
| 32 | Webbing Together 16 Consecutive Regrets | 5 | Perform a 16-hit combo with Spider-Man |
| 33 | Liberty, Justice, and American Juggles | 5 | Perform a 12-hit combo with Captain America |
| 34 | Tentacular Spectacular | 5 | Perform a 16-hit combo with Shuma-Gorath |
| 35 | No Healing Factor Needed | 5 | Perform a 16-hit combo with Wolverine |
| 36 | Hulk Smash!! 16 Smash!! | 5 | Perform a 16-hit combo with Hulk |
| 37 | Twelve Measures of Malevolence | 5 | Perform a 12-hit combo with Blackheart |
| 38 | Carbonadium Catastrophe | 5 | Perform a 12-hit combo with Omega Red |
| 39 | I Actually Feel Pretty Good, Mister Stark | 10 | Finish Arcade mode with Armored Spider-Man on your team (default or higher difficulty) |
| 40 | Extra Credit: Corruption 101 | 10 | Finish Arcade mode with Evil Sakura on your team (default or higher difficulty) |
| 41 | Jet Fuel Doesn't Melt Soviet Steel | 10 | Finish Arcade mode with Mech-Zangief on your team (default or higher difficulty) |
| 42 | Devil in the Details | 10 | Finish Arcade mode with Mephisto on your team (default or higher difficulty) |
| 43 | Shadaloo's Experiment: Success | 10 | Finish Arcade mode with Shadow on your team (default or higher difficulty) |
| 44 | John Walker's Redemption | 10 | Finish Arcade mode with U.S. Agent on your team (default or higher difficulty) |
| 45 | Shining Circuit Gou Rocket Punch Man | 10 | Finish Arcade mode with Cyber-Akuma on your team (default or higher difficulty) |
| 46 | The First Mutant Ascends | 10 | Finish Arcade mode with Apocalypse on your team (default or higher difficulty) |

- "Finish Arcade mode with ... on your team" counts that character as first or second pick.
- "Default or higher difficulty" is the set's own condition: the game's default difficulty setting or a harder one.

## Memory card

- Progress goes into its own save file on the memory card. Without a usable card the game shows "NO MEMORY CARD"
  or "CARD FULL" and "ACHIEVEMENTS NOT SAVED" once after the main menu; unlocks wait until the card can be written.

## When they switch off

As in the X-Men vs. Street Fighter hack: the runtime lives in kernel RAM the BIOS leaves unused, and a boot check
switches the achievements off when something else uses that memory (a PS2 or PS3 in PS1 mode, some loaders). The
game then runs normally.

The command-line builder can leave them out: `--no-achievements` (see [BUILDING.md](../../BUILDING.md)).
