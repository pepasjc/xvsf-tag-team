# Side panel of the patcher page (patcher/make.py reads the sections below; "## " = heading, "- " = item)

## intro: Which games
- **X-Men vs. Street Fighter** (USA, SLUS-00627): tag hack 1.3.
- **Marvel Super Heroes vs. Street Fighter** (USA, SLUS-00793): tag hack 1.0.
- Marvel vs. Capcom (USA, SLUS-01059): in progress, not built by this page yet.
- The page recognises the game from the files on your disc and checks the exact dump by its SHA-1. Other releases (Japan, Europe), already patched images and altered dumps are refused, with the reason.

## mshvsf: What this does
- Arcade and Versus play as a real tag-team game: two full characters per side, the arcade tag rules of the game's own Cross Over mode.
- Tag with **HP + HK** (R1 + R2 by default). A life bar per character; regeneration on the bench only; a knocked-out character is replaced by the partner and the round ends when both are down.
- Every character in a battle plays its own complete sound bank (partners included), rebuilt from your disc.
- Training mode uses the tag rules too, and the secret characters are picked by holding SELECT (Apocalypse: SELECT six times on Akuma).
- START after a won match skips the win quote and the map.
- The CROSS OVER entry of the main menu is gone (this mode replaces it); the version line on the main menu shows the build.

## mshvsf: Restored frames (optional, 8 MB)
- With your arcade ROM set, the image also carries animation frames the PlayStation port dropped, rebuilt from the arcade sprites at build time.
- They are used only when the machine has 8 MB of RAM (DuckStation / SwanStation: Settings → Console → Enable 8MB RAM). The main menu then shows “8MB”, and OPTION MODE has an ARCADE FRAMES ON / OFF line. On a 2 MB console the same image plays as the normal tag hack.

## mshvsf: Achievements
- Built in: 46 achievements adapted from the RetroAchievements set by Lowsun, an ACHIEVEMENTS page in the main menu, unlock popups, progress saved on the memory card.
- On a PS2 or PS3 they switch themselves off and the game runs as usual.

## mshvsf: Speed meter
- OPTION MODE has a SPEED METER line (off by default): a small on-screen gauge of the frame rate, for tests.

## mshvsf: Known issues
- Tested on a real PlayStation (PSIO), MiSTer (2 MB and 8 MB), PSP / PS Vita (Adrenaline) and in emulators. PS3 (tested): runs, achievements switch off automatically; PS2: tested in emulation with a PS2 BIOS (same behaviour).
- Heavy teams can slow down in super moves (the game decodes more sprite data than in the original two-character fights).
- In four-character battles the sound banks may be stored at reduced sample rates on 2 MB, so that all four fit in sound RAM.
