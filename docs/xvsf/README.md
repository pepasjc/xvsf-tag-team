# X-Men vs. Street Fighter: Tag Team Hack (PlayStation)

**Version 1.4**, 2026, by pepa

[![X-Men vs Street Fighter Tag Hack trailer](https://img.youtube.com/vi/aVJAqBGNwyk/maxresdefault.jpg)](https://youtu.be/aVJAqBGNwyk)

Capcom's PlayStation port of X-Men vs. Street Fighter could not keep four characters in memory, so the partner
became an assist and the arcade's tag system was cut. This hack restores the full 2-on-2 tag team on a stock
console. With 8 MB of RAM (modded console, MiSTer or emulator) and your own CPS2 ROM set, it also restores the
arcade animation frames the port cut.

How to build the image: [README](../../README.md#how-to-patch). Other pages: [changelog](CHANGELOG.md),
[achievements](achievements.md), [ARCADE BALANCE](balance.md), [how the patch works](architecture.md),
[engine reference](engine.md).

## What it does

- All four characters loaded in full, no disc access during a fight.
- **Tag** at any time with **HP + HK**: the partner jumps in with an attack and takes over, with its full move set.
- One life bar per character; only the benched character recovers red life.
- A knocked-out character is replaced by its partner. One round; the match ends when both characters of a team
  are down.
- The CPU tags on its own, using the arcade logic. Tagging also works against Apocalypse, from either controller.
- After a team super or a variable counter, the partner who came in stays on point.
- The fight against your own partner after Apocalypse is one on one.
- Music switches to the incoming character's theme after a KO.
- Arcade difficulty ramp and timer speed.
- Default buttons: HP = R1, HK = R2, three punches = L1, three kicks = L2 (tag = R1 + R2). KEY CONFIG still
  changes them.
- Faster battle loading, and a rewritten sprite engine: full speed in normal play, with far less slowdown in
  supers.
- Every character has its full set of voices and sound effects, partners included, and the tag voices play. On
  2 MB, teams of four different characters use slightly lower sample rates to fit.
- **START after a won match** skips the win quote, the character grid and the VS screen and loads the next fight
  (Arcade), or goes back to the select screen sooner (Versus). "PRESS START BUTTON TO SHORT CUT" blinks while it
  is available. The free movement after the KO is on **SELECT** now.
- **VERSUS CPU** in the main menu, below VERSUS MODE: the player who picks it (controller 1 or 2) chooses both
  teams and fights the CPU, at the OPTION MODE difficulty. Achievements do not count there.
- **EX OPTIONS** in the main menu (reset at power-on, except ARCADE BALANCE):
  - **ARCADE BALANCE** (saved with the OPTION MODE memory-card save): OFF keeps the PlayStation rules exactly as
    before; ON plays by the arcade's rules, with half the super meter gain and no super chaining.
    [Details](balance.md).
  - **STAGE ANIM** FULL / OFF: OFF stops the animated stage objects.
  - **ACHIEVEMENT POPUP** ON / OFF.
  - **INFINITE SUPER METER** OFF / ON (default OFF): every fighter's meter stays full, both teams; achievements do
    not unlock while it is ON.
- **Apocalypse's pre-fight dialogue** from the Japanese arcade version, with an English text of our own.
- **The chemical plant explodes on the first knock-out**, as in the arcade.
- **PERFECT** needs the whole team undamaged, as in the arcade.
- **Achievements** built in: 28 achievements written for the tag hack, an ACHIEVEMENTS page in the main menu,
  popups, progress in its own memory card file, and a notice when there is no usable card.
  [The list](achievements.md).

## Restored frames (8 MB)

- **Restored:** Wolverine, Cyclops, Storm, Rogue, Gambit (partly), Sabretooth, Juggernaut, Magneto (partly),
  Dhalsim, Zangief, Cammy, three Ryu sprites, the character select screen and some common effects.
- **Not restored:** Ken, Chun-Li, M. Bison, Akuma, Charlie, Apocalypse.
- Used only when 8 MB is present: the main menu shows "8MB", and EX OPTIONS gets **ARCADE FRAMES ON / OFF**. On
  a 2 MB console the same image plays as the normal tag hack.
- 1.4: Storm, Gambit and Juggernaut have their arcade standing animation again, and Juggernaut his walk forward.
  Every restored animation is checked against the arcade data: it is restored completely or not at all (animations
  that cannot be restored completely keep the PlayStation's frames).
- Characters and menu files stay in memory between fights, so loading is shorter.
- Full sound quality for almost every team, plus Wolverine's tag voice from the arcade set.
- Supported arcade sets: `xmvsf` (Euro 961004), `xmvsfu` (USA 961023), `xmvsfu1d` (with its parent `xmvsf`).

Turning on 8 MB: "Enable 8MB RAM" in DuckStation or SwanStation, the 8 MB RAM option of the MiSTer PSX core, or a
hardware RAM mod on a console.

## Input disc

*X-Men vs. Street Fighter (USA)* (SLUS-00627) as BIN/CUE, matching redump.org:

```
X-Men vs. Street Fighter (USA).bin
Size   392393568
SHA1   c04bf74422c7e1cbb3b961528c38cd67b656856a
```

Convert a `.chd` back first: `chdman extractcd -i game.chd -o game.cue`. Other regions are not supported.

## Expected results

With the default options (the web patcher's result):

```
X-Men vs. Street Fighter (USA) [Tag Hack 1.4].bin          SHA1  f58594231c5e1b835c554cacb89fe28dea60b08b
X-Men vs. Street Fighter (USA) [Tag Hack 1.4 + Restored Frames].bin
  with xmvsfu (+ xmvsf)                                    SHA1  2278e1166ef0c1ec2c6c6044b082d19454052e03
  with xmvsf or xmvsfu1d                                   SHA1  0fdbe71238b54fadfc7773102e09c7f16f91ff29
```

Without achievements (command line, `--no-achievements`): 2 MB `12a0282645a6544eb5a21f62fb517a64f15af506`,
with `xmvsfu` `dc78011f190646a8c2944223bcad601b2340b708`, with `xmvsf` or `xmvsfu1d` `5781e612cbd3c2a73206a624477a7a28f9f1717e`.

Both the web patcher and the command line check the result. Other command-line options have their own reference
hashes (`builder/data/known.json`).

## Compatibility

Tested on a real PlayStation (PSIO), MiSTer (2 MB and 8 MB), PSP / PS Vita (Adrenaline) and in emulators
(Beetle PSX, SwanStation). PS3 (tested): runs, achievements switch off automatically; PS2: tested in emulation
with a PS2 BIOS (same behaviour).
