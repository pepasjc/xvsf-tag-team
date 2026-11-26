# Marvel Super Heroes vs. Street Fighter: Tag Team Hack (PlayStation)

**Version 1.1**, 2026, by pepa

[![Marvel Super Heroes vs Street Fighter Tag Hack trailer](https://img.youtube.com/vi/ms0N8HAE9A0/maxresdefault.jpg)](https://youtu.be/ms0N8HAE9A0)

On the PlayStation, Marvel Super Heroes vs. Street Fighter only lets you tag in CROSS OVER mode, where both teams
are the same two characters. In Arcade and Versus the partner is a cut-down assist. This hack makes every Arcade,
Versus and Training match a real 2-on-2 tag battle with four different, complete characters, on a stock 2 MB
PlayStation.

How to build the image: [README](../../README.md#how-to-patch). Other pages: [changelog](CHANGELOG.md),
[achievements](achievements.md), [how the patch works](technical.md), [engine reference](engine.md).

## What it does

- **2v2 tag in every match.** Four full characters are loaded for every Arcade, Versus and Training fight, with
  no disc access during the fight. There is no fallback to the cut-down partner: every team fits on every stage
  (checked for all 235,313 team and stage combinations, secret characters included).
- **The arcade tag rules**, taken from the game's own Cross Over mode: tag with **HP + HK** (R1 + R2 by
  default), one life bar per character, only the benched character recovers red life, a knocked-out character is
  replaced by the partner, one round that ends when both characters of a team are down; time over goes to the
  team with more life. The CPU tags. Variable Counter and Variable Combination (team super) work as in the arcade.
  After a knock-out the music switches to the incoming character's theme.
- **Full sound for every character.** Partners play their own complete sound bank (in the original they only had
  a few assist sounds, so a tagged-in character was mostly silent). Voices keep their original quality; to fit
  four banks into sound memory, some sound effects use a lower sample rate on 2 MB.
- **Speed.** A rewritten sprite decoder and memory routines, plus decode-ahead: the next animation frames are
  unpacked while the game waits for the video frame. Typical teams run at full speed in normal play.
- **Secret characters.** Hold SELECT and confirm on a character: Akuma becomes Cyber-Akuma (solo, as in the
  arcade), and Blackheart, Hulk, Dhalsim, Bison, Omega Red and Spider-Man become Mech-Zangief, Dark Sakura,
  Shadow, U.S. Agent, Mephisto and Armored Spider-Man, as main or partner. Apocalypse: tap SELECT six times on
  Akuma, then confirm. No memory-card unlock needed.
- **Training mode:** the dummy picks a partner like you do, and training uses the tag rules.
- **START after a won match** skips the win quote and the map and loads the next fight (Arcade), or goes back to
  the select screen sooner (Versus). Opponents, stages, scores and the ending are the same as without it. "PRESS
  START BUTTON TO SHORT CUT" blinks after a win.
- **Achievements** built in: 46 achievements adapted from the RetroAchievements set by Lowsun, an ACHIEVEMENTS
  page in the main menu, popups, progress in its own memory card file. [The list](achievements.md).
- **VERSUS CPU** in the main menu, below VERSUS: the player who picks it (controller 1 or 2) chooses both teams
  and fights the CPU, at the OPTION difficulty. Achievements do not count there.
- **EX OPTIONS** in the main menu (not saved; reset at power-on): **STAGE ANIM** ON / OFF, **ACHIEVEMENT POPUP**
  ON / OFF, **ARCADE BALANCE** OFF / ON (default OFF; ON = the arcade's super meter gain, meter when blocking,
  counter hits and per-character defence) and **INFINITE SUPER METER** OFF / ON (default OFF; ON keeps every
  fighter's meter full, both teams; achievements do not unlock while it is ON).
- **Norimaro** is selectable (he is complete on the US disc; only the links into his select-screen cell were cut),
  with an English ending text of our own.
- **Menus:** CROSS OVER is removed from the main menu (every mode is a tag mode now).
- **Boot cards:** PEPA SOFT HOUSE, then a notice that this is a free fan patch (portraits taken from your disc).
  The main menu shows the version, "TAG HACK 1.1".

## 8 MB

Give the patcher your own arcade ROM set too (`mshvsf`, or a clone such as `mshvsfu` together with `mshvsf`;
every supported set gives the same frames) and the image carries the 8 MB loader. On a machine with 8 MB of RAM
(emulator option, MiSTer, modified console) it then uses the extra memory:

- all four characters in their original sprite format (no slower encodings), cached between fights for shorter
  loading, and full-quality sound;
- animation frames the PlayStation port dropped, rebuilt from the arcade graphics at build time (every restored
  animation is checked against the arcade data: an animation is restored completely or not at all);
- **enhanced voices**: the character and announcer voices are streamed from the extra memory instead of sharing the
  sound chip's memory, so they play at full quality, and with an arcade set 345 of them are the arcade's own
  recordings (higher sample rate, full length) converted at build time;
- "8MB" before the version line on the main menu.

The 8 MB images have every 1.1 feature (EX OPTIONS, VERSUS CPU, Norimaro, ARCADE BALANCE, INFINITE SUPER METER).

Restored frames by character:

- **Restored:** Cyclops, Captain America, Hulk, Wolverine, Shuma-Gorath, Omega Red, Spider-Man, Blackheart,
  Dhalsim, Zangief, Sakura, Norimaro, Cyber-Akuma, Mech-Zangief and Dark Sakura; a few frames for Ryu and Ken.
- **Not restored:** Apocalypse, Chun-Li,
  M. Bison, Akuma, Dan, Shadow.

On a 2 MB console the same image plays as the normal tag hack. The image built from the disc alone always plays as
the 2 MB hack. The command-line builder can also make an image with the 8 MB loader but without an arcade set
(`--ram8`).

Turning on 8 MB: "Enable 8MB RAM" in DuckStation or SwanStation, the 8 MB RAM option of the MiSTer PSX core, or a
hardware RAM mod on a console. Beetle PSX has no 8 MB mode.

## Input disc

*Marvel Super Heroes vs. Street Fighter (USA)* (SLUS-00793) as BIN/CUE, matching redump.org:

```
Marvel Super Heroes vs. Street Fighter (USA).bin
Size   552894048
SHA1   6e50ac0d4dfc5eaf2ddd0da3cabde19e0ec3721a
```

CHD, PBP, ECM and ISO must be converted back to BIN/CUE first. Japanese and European discs are refused.

The result is larger than the original disc (about 640 MB, 61 minutes; a little more with restored frames):
character data is appended after the original data. It still fits an 80-minute CD-R.

## Expected results

With the default options (the web patcher's result):

```
Marvel Super Heroes vs. Street Fighter (USA) [Tag Hack 1.1].bin    SHA1  0c782cd7f2addad8a13334de3ab76295eaac1c45
Marvel Super Heroes vs. Street Fighter (USA) [Tag Hack 1.1 + Restored Frames].bin
  with mshvsf (or mshvsfu + mshvsf)                                 SHA1  ae2f516685afd86972568c15c7bdeac6daa6fbfe
```

Command line: the 8 MB loader without an arcade set (`--ram8`, "[Tag Hack 1.1 8 MB]"; stock voices, streamed) `0d28aa3902a1e65f4c80b3173bb960474a70df29`.
Without achievements (`--no-achievements`): 2 MB `faeea6e8c08c703a20b99c3d9126377e4c9ab90f`, `--ram8` `3df681f805e1158c05b5d69aeb8e75ce1be2a61a`.

## Compatibility

Tested on a real PlayStation (PSIO), MiSTer (2 MB and 8 MB), PSP / PS Vita (Adrenaline) and in emulators
(Beetle PSX, SwanStation). PS3 (tested): runs, achievements switch off automatically; PS2: tested in emulation
with a PS2 BIOS (same behaviour).

## Known issues

- Heavy teams slow down in supers and team supers, more than the original's two-character fights: the game has
  to unpack more sprite data. The 8 MB mode avoids most of this.
- On 2 MB some sound effects play at a lower sample rate in four-character fights.
- When the final-boss fix fires (your partner on point at the knock-out), only the partner appears in the
  post-fight dialogue.
- One or two players: there is no multitap support.
- In about 0.07 % of teams (one character of a very large team on the tightest stages) a few sprite tiles that
  never showed up in testing are left blank to make the team fit.
