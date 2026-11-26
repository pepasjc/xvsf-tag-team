# X-Men vs. Street Fighter Tag Team Hack: changelog

## 1.4 (2026)

A VERSUS CPU mode, an EX OPTIONS menu, cut arcade content restored, and fixes.

- Main menu: **VERSUS CPU**, right below VERSUS MODE. The player who confirms it (controller 1 or 2) picks both
  teams; the other side is played by the CPU, at the difficulty set in OPTION MODE. VERSUS MODE itself is
  unchanged (two players). Achievements do not count in VERSUS CPU.
- Main menu: **EX OPTIONS** (not saved, reset at power-on):
  - ARCADE BALANCE OFF / ON (moved here from OPTION MODE; still saved with the OPTION MODE memory-card save).
  - STAGE ANIM FULL / OFF: OFF stops the animated stage objects, which saves time in heavy scenes.
  - ACHIEVEMENT POPUP ON / OFF.
  - INFINITE SUPER METER OFF / ON (default OFF): every fighter's meter stays full, both teams; achievements do not
    unlock while it is ON.
  - 8 MB: ARCADE FRAMES ON / OFF is an EX OPTIONS row now; OPTION MODE is the game's own again.
- **Apocalypse's pre-fight dialogue** from the Japanese arcade version is back, with an English text of our own
  (drawn with the game's own font from your disc).
- **The chemical plant explodes on the first knock-out**, as in the arcade (the stage changes in the middle of the
  fight).
- **PERFECT** needs the whole team undamaged, as in the arcade (it was given when only the last character standing
  was undamaged).
- 8 MB: Storm, Gambit and Juggernaut no longer stand still in their idle pose; Juggernaut's walk forward is
  animated again. Every restored animation is now checked against the arcade data and restored completely or not at
  all (Gambit, Magneto and two of Storm's animations mixed arcade and PlayStation frames in 1.3).
- Achievement "Last One Standing" now needs the win to come from your second character after your first pick was
  knocked out (it also unlocked when the second pick had been knocked out).
- Removed the 1.1 decode-ahead predictor routine: it had nothing left to predict since 1.2 and could in rare
  cases jump into memory that another part of the game had reused.
- One or two players, as in the original game: there is no multitap support.
- Version line TAG HACK 1.4.

## 1.3 (2026)

Fixes for the bugs reported on 1.2, a faster after-match flow, an ARCADE BALANCE option and built-in achievements.

- A team super or variable counter with HP + HK held no longer tags the incoming character back out when the
  buttons are released: a tag needs a new press.
- The life-bar portrait follows the character on point after a tag.
- Arcade played from controller 2: the Apocalypse fight loads both of your characters in full, and tagging works.
  With 8 MB this one fight uses the 2 MB loader (the port's frames).
- START after a won match skips the win quote, the grid and the VS screen and loads the next fight (Arcade), or
  goes back to the select screen sooner (Versus). The free movement after the KO moved from START to SELECT.
- OPTION MODE: ARCADE BALANCE (default OFF, saved on the memory card). OFF = the PlayStation rules as before; ON =
  the arcade's rules: half the super meter gain, no super chaining. See [balance.md](balance.md).
- Built-in achievements: 28 achievements, an ACHIEVEMENTS page in the main menu, popups, their own memory card
  file, and notices when the card is missing or full. They switch themselves off on a PS2 or PS3 and wherever
  something else uses their memory. See [achievements.md](achievements.md).
- Boot card: "Follow me @pepasjc". Version line TAG HACK 1.3 (on 8 MB, "8MB" on the line below).
- Web patcher: no options any more (disc, optionally the arcade ROM set, build); English and Brazilian Portuguese.
  The command-line builder keeps the advanced options.

## 1.2 (2026)

- Partners load their full sound bank: a tagged-in or replacement character has all its own voices and
  sound effects (before, most were silent).
- The tag voices play (they were silent on the PS1 for every character), as do Juggernaut's KO scream,
  Wolverine's throw sound and an Akuma voice that were missing from the fight banks.
- 2 MB: teams of four different characters fit by lowering some sample rates, never below the port's
  lowest. 8 MB: full quality for almost every team, and Wolverine's tag voice from the arcade set.
- 8 MB: the menu could show the version of a previously played build after a MiSTer core reload; the
  8 MB module is now always read from the disc at boot.
- The builder and web patcher contain no code from the game: the few original instructions the patch
  keeps are taken from your own disc at build time.

## 1.1 (2026)

- Much faster on a stock 2 MB console: the sprite engine is rewritten in optimised MIPS. Walking, normals
  and most specials run at full speed with four characters loaded; supers slow down far less.
- 8 MB: characters are decoded during loading, so supers with restored frames are much smoother.
- After a team super or a variable counter, the partner who came in stays on point, as in the arcade.
- Fixed: specials and supers did not work after a variable counter.
- The fight against your own partner after Apocalypse is one on one: one life bar per side, no tag,
  one round (issue #1).
- New boot card: a notice that this is a free fan patch. The first card shows only PEPA SOFT HOUSE.
- The builder and web patcher no longer need a compiler.

## 1.0.1 (2026)

- Fixes a freeze on real PlayStation hardware: with the image built with restored frames, a stock 2 MB
  console could hang while loading the character select screen. The check for 8 MB of RAM no longer
  writes anything when the memory is mirrored 2 MB. Emulators and the MiSTer were not affected.
- Version line reads TAG HACK 1.0.1.

## 1.0 (2026)

First release.

- Tag team on a stock 2 MB console: four full characters, tag with HP + HK, two life bars per side,
  regeneration on the bench only, KO replacement, single-round matches, the CPU tags, tag against
  Apocalypse, the incoming character's theme after a KO, arcade difficulty ramp and timer speed,
  modern default buttons.
- Restored animation frames for 8 MB machines, built from the user's arcade ROM set: eleven characters,
  the select screen, some common effects; ARCADE FRAMES ON / OFF in OPTION MODE.
- Shorter loading with 8 MB: characters and the select-screen files stay in memory between fights.
- Builder (command line) and web patcher with reproducible results.
