# Side panel of the patcher page (patcher/make.py reads the sections below; "## " = heading, "- " = item)

## intro: Which games
- **X-Men vs. Street Fighter** (USA, SLUS-00627): tag hack 1.4.
- **Marvel Super Heroes vs. Street Fighter** (USA, SLUS-00793): tag hack 1.1.
- Marvel vs. Capcom (USA, SLUS-01059): in progress, not built by this page yet.
- The page recognises the game from the files on your disc and checks the exact dump by its SHA-1. Other releases (Japan, Europe), already patched images and altered dumps are refused, with the reason.

## mshvsf: What this does
- Arcade and Versus play as a real tag-team game: two full characters per side, the arcade tag rules of the game's own Cross Over mode.
- Tag with **HP + HK** (R1 + R2 by default). A life bar per character; regeneration on the bench only; a knocked-out character is replaced by the partner and the round ends when both are down.
- Every character in a battle plays its own complete sound bank (partners included), rebuilt from your disc.
- Training mode uses the tag rules too, and the secret characters are picked by holding SELECT (Apocalypse: SELECT six times on Akuma).
- START after a won match skips the win quote and the map.
- **VERSUS CPU** in the main menu (below VERSUS): the player who picks it chooses both teams and fights the CPU.
- **EX OPTIONS** in the main menu: STAGE ANIM, ACHIEVEMENT POPUP, ARCADE BALANCE (the arcade's meter and defence rules, default OFF) and INFINITE SUPER METER (default OFF; achievements do not unlock while it is ON).
- **Norimaro** is selectable, with an English ending text of our own.
- Fixed in 1.1: the freeze after the final boss when the partner was on point at the knock-out.
- The CROSS OVER entry of the main menu is gone (this mode replaces it); the version line on the main menu shows the build.

## mshvsf: Restored frames (optional, 8 MB)
- With your arcade ROM set, the image also carries animation frames the PlayStation port dropped, rebuilt from the arcade sprites at build time.
- The 8 MB image has every 1.1 feature, plus **enhanced voices**: voices are streamed from the extra memory at full quality, and 345 voice samples are the arcade's own recordings (about 12 kHz, full length), converted at build time from your ROM set. Every restored animation is checked against the arcade data (restored completely or not at all).
- They are used only when the machine has 8 MB of RAM (DuckStation / SwanStation: Settings → Console → Enable 8MB RAM). The main menu then shows “8MB”. On a 2 MB console the same image plays as the normal tag hack.

## mshvsf: Achievements
- Built in: 46 achievements adapted from the RetroAchievements set by Lowsun, an ACHIEVEMENTS page in the main menu, unlock popups, progress saved on the memory card.
- On a PS2 or PS3 they switch themselves off and the game runs as usual.

## mshvsf: Known issues
- Tested on a real PlayStation (PSIO), MiSTer (2 MB and 8 MB), PSP / PS Vita (Adrenaline) and in emulators. PS3 (tested): runs, achievements switch off automatically; PS2: tested in emulation with a PS2 BIOS (same behaviour).
- Heavy teams can slow down in super moves (the game decodes more sprite data than in the original two-character fights).
- In four-character battles the sound banks may be stored at reduced sample rates on 2 MB, so that all four fit in sound RAM.
