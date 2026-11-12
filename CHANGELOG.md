# Changelog

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
