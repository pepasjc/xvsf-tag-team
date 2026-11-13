"""1.1 engine speed-ups (tools/speed/*): one entry point for the disc builders.

    exe_patches()          [(ram_addr, bytes)] for the US executable: upload + quad + frame
                           (the decoders come through nsppatch.patches(), which returns tools/speed/decode
                           unless --nospeed is given)
    apply_overlays(read, write, lmap)   stage overlay patches (BG tile layers) written into P/P4/STAGEn.BIN
                           in the image itself, before the battle layout copies the stage files.
Disabled with --nospeed (then the image is the 1.0.x one)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "speed"))
OVL_BASE = 0x80098000
MODULES = tuple(m for m in os.environ.get("XV_SPEED", "decode,upload,quad,frame,logic").split(",") if m and m != "decode")


def enabled():
    return "--nospeed" not in sys.argv


def _mods():
    import importlib
    return [importlib.import_module(m) for m in MODULES]


def exe_patches():
    if not enabled(): return []
    out = []
    for m in _mods():
        out += list(m.patches())
    # no two modules may write the same byte
    spans = sorted((a, a + len(d)) for a, d in out)
    for (a0, b0), (a1, b1) in zip(spans, spans[1:]):
        assert b0 <= a1, "speed patches overlap at %08x" % a1
    return out


def decode_patches():
    if "decode" not in os.environ.get("XV_SPEED", "decode,upload,quad,frame,logic").split(","):
        return None
    import decode
    return list(decode.patches())


def apply_overlays(file_read, file_write):
    """file_read(path, off, n) / file_write(path, off, data) on the image's ISO files (path as in the LBA map)"""
    if not enabled() or "frame" not in MODULES: return 0
    import frame
    n = 0
    for path, lst in frame.ovl_patches().items():
        for addr, data in lst:
            off = addr - OVL_BASE
            assert off >= 0
            file_write(path, off, data); n += 1
    return n
