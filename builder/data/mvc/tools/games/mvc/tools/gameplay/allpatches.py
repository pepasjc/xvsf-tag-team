"""Overlay (DAT/*.ARC) patches of the MvC gameplay layer, for the disc builders (tools/tagload/mktag.py).
EXE patches stay in tagmode.py / assist.py (mktag applies those itself).

    overlay_patches(version=None, assist=False) -> [(file name, file offset, bytes)]   (file names as in work/lba_map.json)
    check(read, assist=False)       read(file name) -> bytes of the stock file; asserts stock words first

selscreen.py  SEL01.ARC: no special partner (TYPE SELECT skipped), secret characters open + HOLD SELECT on the base
              character, 4-portrait VS screen, ARCADE CPU partner chosen before the VS screen
menus.py      OPDEMO.ARC: CROSS OVER removed from the main menu, version line
assistsel.py  SEL01.ARC, only with assist=True (mktag.py --assistsel): stock special-partner roulette after the partner
              pick, ARCADE CPU random assist (2 characters + 1 assist per side)
"""
import selscreen, menus


def overlay_patches(version=None, assist=False):
    out = selscreen.overlay_patches() + menus.overlay_patches(version or menus.DEFAULT)
    if assist:
        import assistsel
        out += assistsel.overlay_patches()          # after selscreen's: replaces its `jal vsinit` word
    return out


def check(read, assist=False):
    selscreen.check_file(read(selscreen.FILE))
    menus.check_file(read(menus.FILE))
    if assist:
        import assistsel
        assistsel.check_file(read(assistsel.FILE))
