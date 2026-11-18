"""All MSHvSF gameplay patches in one place, for the disc builder and the test harnesses.

    patches()          [(addr, bytes)] for SLUS_007.93
    overlay_patches()  [(file, offset, bytes)] for files on the disc (OPDEMO.BIN: version line)
    apply_ram(emu)     poke everything (call at the title / main menu, before a battle starts)
    apply_exe(exe)     bytearray of SLUS_007.93, checked against the stock words

title=None leaves the version line out (like XvSF --no-menu-version).
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tagmode, menuversion, pad, menus, cyber, training

EXE_BASE, EXE_HDR = 0x80010000, 0x800


def patches(title=menuversion.DEFAULT, msyms=None):
    """msyms: tools/speed/meter.py symbols when the meter is built in (battle-init tail + SPEED METER option line)"""
    out = (tagmode.patches(tail=msyms["mcopy"] if msyms else None) + pad.patches() + menus.patches(msyms) + cyber.patches()
           + training.patches())
    if title:
        out += menuversion.patches(title)
    return out


def overlay_patches(title=menuversion.DEFAULT, msyms=None):
    return ((menuversion.overlay_patches(title) if title else []) + menus.overlay_patches(msyms) + cyber.overlay_patches()
            + training.overlay_patches())


def apply_ram(emu, title=menuversion.DEFAULT):
    pad.apply_ram(emu)
    tagmode.apply_ram(emu)
    if title:
        menuversion.apply_ram(emu, title)


def apply_exe(exe: bytearray, title=menuversion.DEFAULT):
    tagmode.check_orig(lambda a: struct.unpack_from("<I", exe, a - EXE_BASE + EXE_HDR)[0])
    pad.check_orig(lambda a, n: bytes(exe[a - EXE_BASE + EXE_HDR:a - EXE_BASE + EXE_HDR + n]))
    for addr, data in patches(title):
        o = addr - EXE_BASE + EXE_HDR
        exe[o:o + len(data)] = data
    return exe


if __name__ == "__main__":
    for addr, data in patches():
        print(f"{addr:08x} {len(data):4d} {data[:16].hex()}")
    for f, off, data in overlay_patches():
        print(f"{f} +{off:x} {data.hex()}")
