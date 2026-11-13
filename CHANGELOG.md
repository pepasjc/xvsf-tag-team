# Changelog

## 1.1 (2026)

- Much faster on a stock 2 MB console. The sprite pipeline was rewritten in hand-optimised MIPS: tile
  decoders, the sprite memory allocator and the upload to video memory, the sprite quad builder, the main
  loop and GPU queue, the stage background layers, the memory copy routines and parts of the game logic.
  Pictures and game logic are unchanged; only the time they take. Walking, normals and most specials now
  run at full speed with four characters loaded, and supers drop far less than in 1.0.1.
- Characters that need the densest sprite encoding keep their most used tiles in the fast format.
- 8 MB: the four characters of a fight are decoded during the loading screen, so fights decode almost
  nothing; supers with restored frames are much smoother. Loading takes about one second longer.
- After a team super (variable combination) the partner who jumped in stays on point, as in the arcade.
- After a variable counter the partner who came in stays on point, as in the arcade, and keeps all its
  special moves and supers (they were blocked after a counter).
- The fight against your own partner after Apocalypse is one on one again: one character and one life
  bar per side, no tag, team super or counter, one round (issue #1).
- A second boot card: a short notice that this is a free fan-made patch, with the project's address.
  Its portraits are taken from your own disc when the patch is built. The first card now shows only
  PEPA SOFT HOUSE.
- The builder and the web patcher no longer compile anything: all of the patch's own code ships
  prebuilt and checked by its SHA-1.
- Version line reads TAG HACK 1.1.

## 1.0.1 (2026)

- Fixes a freeze on real PlayStation hardware: with the image built with restored frames, a stock 2 MB
  console could hang while loading the character select screen. The check for 8 MB of RAM no longer
  writes anything when the memory is mirrored 2 MB, and runs only once per boot. Emulators and the MiSTer
  were not affected.
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
