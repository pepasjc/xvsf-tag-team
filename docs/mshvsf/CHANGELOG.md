# Marvel Super Heroes vs. Street Fighter Tag Team Hack: changelog

## 1.1 (2026)

A VERSUS CPU mode, an EX OPTIONS menu, Norimaro, the arcade's balance as an option, and fixes for the bugs reported
on 1.0. The 8 MB images get every 1.1 feature plus enhanced voices.

- Main menu: **VERSUS CPU**, right below VERSUS. The player who confirms it (controller 1 or 2) picks both
  teams; the other side is played by the CPU, at the difficulty set in OPTION. VERSUS itself is unchanged (two
  players). Achievements do not count in VERSUS CPU.
- Main menu: **EX OPTIONS** (not saved, reset at power-on):
  - STAGE ANIM ON / OFF: OFF stops the animated stage objects, which saves time in heavy scenes.
  - ACHIEVEMENT POPUP ON / OFF.
  - **ARCADE BALANCE** OFF / ON, default OFF. OFF keeps the PlayStation rules; ON plays by the arcade's rules for
    super meter gain, the meter gained when blocking, counter hits and each character's defence.
  - **INFINITE SUPER METER** OFF / ON, default OFF: ON keeps every fighter's super meter full (both teams, CPU
    included). Achievements do not unlock while it is ON.
- **Norimaro** is selectable: he is complete on the US disc, only the links into his select-screen cell were cut.
  His ending gets an English text of our own (the US disc has a copy of Dan's line there).
- The SPEED METER is no longer an option (OPTION is the game's own screen again; the pause menu is the game's own).
- Fixed: a freeze after beating the final boss in Arcade when the partner was on point at the knock-out (2 MB and
  8 MB). The main character is now put back on point before the ending scene loads; in that case only the partner
  appears in the post-fight dialogue.
- Sprite data packed by frame group: a little less slowdown in heavy scenes.
- Loader: a latent issue found in the Marvel vs. Capcom port (stale data copied at battle start) is fixed here too.
- One or two players, as in the original game: there is no multitap support.
- Version line TAG HACK 1.1.
- **8 MB** (with an arcade set, or `--ram8`): the same 1.1 game, plus
  - **enhanced voices**: voices are streamed from the extra memory into the sound chip as they play, so they no
    longer compete with the effects for its memory and play at full quality; with an arcade set 345 voice samples
    are the arcade's own recordings (12 kHz instead of 3-9 kHz, at their full length), converted at build time;
  - restored frames as in 1.0, now checked against the arcade data animation by animation (fixed: Blackheart's walk
    forward and back mixed arcade and PlayStation frames); ARCADE FRAMES is no longer an option (always on with
    8 MB);
  - fixed: losing to the final boss, continuing and picking a team again hung on the loading screen (8 MB only).

## 1.0 (2026)

First release.

- Every Arcade, Versus and Training match is a 2-on-2 tag battle with four full characters on a stock 2 MB
  PlayStation; every team fits on every stage, with no fallback to the cut-down partner.
- The arcade tag rules of the game's own Cross Over mode: tag with HP + HK, a life bar per character, red-life
  recovery on the bench only, KO hand-over, one round, Variable Counter and Variable Combination, a CPU that tags,
  the incoming character's theme after a KO.
- Every character plays its own full sound bank, partners included; voices at the original quality.
- Rewritten sprite decoder and memory routines, decode-ahead; SPEED METER option.
- Secret characters by holding SELECT (Apocalypse: SELECT six times on Akuma); no unlock needed.
- Training mode with tag teams on both sides.
- START after a won match skips the win quote and the map.
- Built-in achievements: 46, adapted from the RetroAchievements set by Lowsun.
- CROSS OVER removed from the main menu; boot cards; version line TAG HACK 1.0.
- Built with your arcade ROM set, on 8 MB: all characters in the original sprite format, cached between fights,
  full-quality sound, restored animation frames and ARCADE FRAMES ON / OFF.
- Built by the same web patcher and command-line builder as the X-Men vs. Street Fighter hack.
