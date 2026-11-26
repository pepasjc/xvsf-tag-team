# Marvel vs. Capcom: Tag Team Hack (PlayStation)

**Version 1.0**, 2026, by pepa

[![Marvel vs. Capcom Tag Hack trailer](https://img.youtube.com/vi/Rak99vGtD7g/maxresdefault.jpg)](https://youtu.be/Rak99vGtD7g)

The PlayStation port of Marvel vs. Capcom: Clash of Super Heroes only keeps the arcade's tag battles in CROSS OVER
mode; in Arcade and Versus the partner is a special partner (assist) only. This hack makes every Arcade and Versus
match a real 2-on-2 tag battle with four different, complete characters plus a special partner, on a stock 2 MB
PlayStation.

How to build the image: [README](../../README.md#how-to-patch). Other pages: [changelog](CHANGELOG.md).

## What it does

- **Tag battles in every Arcade and Versus match.** Tag with **HP + HK** (R1 + R2 by default), one life bar per
  character, red-life recovery on the bench, a knocked-out character is replaced by the partner. The CPU tags at
  about the arcade's rate (the PlayStation CPU almost never did).
- **Special partners (assists)** in every tag battle. EX OPTIONS **ASSISTS**: **ROULETTE** (default: the arcade's
  roulette, button codes included), **NORMAL** (pick from the grid) or **OFF** (fastest for heavy teams).
- **Onslaught is playable** in Versus and Arcade, with his own ending. In Arcade you fight on the normal stage
  rotation, the select screen shows him on his secret cell, his damage is scaled for a playable fighter (the CPU
  boss is unchanged), and the stage music comes back after a knock-out.
- **Variable Cross** (Duo Team Attack): quarter-circle back + HP + HK at super level 2 or more, and your real tag
  partner joins the attack. The cut-in screen is skipped; the attack starts after the super flash.
- **VERSUS CPU** in the main menu, right below VERSUS: the player who confirms it (controller 1 or 2) picks both
  teams; the other side is played by the CPU at the OPTION difficulty. Achievements do not count in VERSUS CPU.
- **EX OPTIONS** in the main menu, saved with the game's own memory card save:
  - **STAGE ANIM** ON / OFF;
  - **INTRO** SIMPLE / STOCK (SIMPLE skips the slow character intro animations; default on 2 MB);
  - **ACHIEVEMENT POPUP** ON / OFF;
  - **ASSISTS** ROULETTE / NORMAL / OFF;
  - **ARCADE BALANCE** OFF / ON, default OFF: ON = the arcade's meter gain when blocking and its red-life minimum;
  - **INFINITE SUPER METER** OFF / ON, default OFF (achievements do not unlock while it is ON).
- **Achievements** built in: 75 achievements adapted from the RetroAchievements set by SherryBirkin, an
  ACHIEVEMENTS page in the main menu, popups, progress in its own memory card file.
- **Voices:** every partner and assist plays its own sound bank; voices get a clarity and loudness correction where
  four banks share the sound memory.
- **Speed:** a rewritten sprite decoder, decode-ahead and a VRAM tile cache keep typical teams at full speed in
  normal play.
- **Boot cards:** PEPA SOFT HOUSE, then a notice that this is a free fan patch. The main menu shows the version,
  "TAG HACK 1.0".

## 8 MB

Give the patcher your own arcade ROM set too (`mvsc`) and the image carries the 8 MB loader. On a machine with 8 MB
of RAM (emulator option, MiSTer, modified console) it then uses the extra memory:

- **arcade animation frames**: frames the port cut, converted at build time from your ROM set and checked against
  the arcade data animation by animation (EX OPTIONS > **ARCADE FRAMES** ON / OFF; the INTRO row becomes this row,
  intros are always full on 8 MB);
- **full-resolution effects** (the 2 MB image draws some, such as Spider-Man's web, at half resolution) and full
  character intros; characters cached between fights;
- **arcade voices**: voices are streamed from the extra memory at full quality, with the arcade's own recordings
  where they match the PlayStation samples, converted at build time from your ROM set;
- "8MB" before the version line on the main menu.

On a 2 MB console the same image plays exactly like the 2 MB image (it carries both; the 8 MB parts only switch on
when 8 MB of RAM is found).

Turning on 8 MB: "Enable 8MB RAM" in DuckStation or SwanStation, the 8 MB RAM option of the MiSTer PSX core, or a
hardware RAM mod on a console. Beetle PSX has no 8 MB mode.

## Input disc

*Marvel vs. Capcom: Clash of Super Heroes (USA)* (SLUS-01059) as BIN/CUE, matching redump.org:

```
Marvel vs. Capcom - Clash of Super Heroes (USA).bin
Size   428212176
SHA1   b0301419874638bd86689cfbbde6a901585587d0
```

CHD, PBP, ECM and ISO must be converted back to BIN/CUE first. Other regions are refused.

The result is larger than the original disc (about 636 MB; a little more with an arcade set): character data is
appended after the original data. It still fits an 80-minute CD-R.

## Expected results

```
Marvel vs. Capcom (USA) [Tag Hack 1.0].bin                    SHA1  121dd8158da5aadb2b6df85eeaf0ae143c9d7c29
Marvel vs. Capcom (USA) [Tag Hack 1.0 8MB].bin   with mvsc   SHA1  6423a1466e0a798ee8fa1ea4782eddcdad24a205
```

## Compatibility

Tested on a real PlayStation (PSIO), MiSTer and in emulators (Beetle PSX, SwanStation 2 MB and 8 MB). PS3 / PS2:
achievements, assists and the VERSUS CPU row switch off automatically; PS2 tested in emulation with a PS2 BIOS.

## Known issues

- Heavy teams slow down in supers and team supers, more than the original's two-character fights: the game has to
  unpack more sprite data. ASSISTS OFF and the 8 MB mode help.
- One or two players: there is no multitap support.
