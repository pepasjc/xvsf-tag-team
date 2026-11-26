"""MvC 8 MB "dual blob" image from the builder's two overlays: games/mvc/tools/ap8/dual8.py (the MvC 8 MB agent's tool,
user rule 2026-11-24: an 8 MB disc in 2 MB mode must behave exactly like the 2 MB disc) on cdrom.Overlay objects.

    compose(ov2, ov8) -> Overlay
ov2 = the 2 MB build, ov8 = the 8 MB build with the SAME flags.  Below ov2's end they differ only in the EXE and the loader
blob item; OUT = ov2 (EXE, blob) + ov8's appended 8 MB items at the same sectors + ov8's 8 MB blob as a new item at the end +
the boot chain: old exit (j 0x800106e0 -> BOOT8) -> DUAL: open-bus-proof 8 MB test; 8 MB: blob entry -> the 8 MB blob +
ov8's other EXE words; both: WIPE to 0x801ff800, j BOOT8 (ov8's boot stub, its exit -> WIPE)."""
import os, struct, sys
import numpy as np
from xvb import cdrom

SECTOR = cdrom.SECTOR
EXE_BASE, EXE_HDR = 0x80010000, 0x800
BLOBENT, ENTRY = 0x8001b4d4, 0x800106e0
BOOT8, DUAL, WIPE_AT, ZEND = 0x8014d800, 0x8014da00, 0x801ff800, 0x8014e000


class _Dov(cdrom.Disc):
    def __init__(self, ov): self.f = cdrom.OverlayFile(ov)


def _j(t): return 0x08000000 | (t >> 2 & 0x3FFFFFF)
def _bcd(x): return (x // 10) << 4 | x % 10
def msf_word(lba):
    l = lba + 150
    return _bcd(l // 4500) | _bcd(l // 75 % 60) << 8 | _bcd(l % 75) << 16
def lba_of(m):
    u = lambda b: (b >> 4) * 10 + (b & 15)
    return u(m & 0xff) * 4500 + u(m >> 8 & 0xff) * 75 + u(m >> 16 & 0xff) - 150


def compose(ov2, ov8, log=print):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
    from mipsasm import Asm
    D2, D8 = _Dov(ov2), _Dov(ov8)
    n2, n8 = ov2.nsec, ov8.nsec
    fa = {n.split("/")[-1]: (l, s) for n, l, s in D2.walk()}
    fb = {n.split("/")[-1]: (l, s) for n, l, s in D8.walk()}
    la, sz = fa["SLUS_010.59"]; assert fb["SLUS_010.59"] == (la, sz), "EXE location differs"
    E2 = bytearray(D2.read(la, sz)); E8 = D8.read(la, sz)
    off = lambda a: a - EXE_BASE + EXE_HDR
    w = lambda E, a: struct.unpack_from("<I", E, off(a))[0]
    bmsf, bsz = w(E8, BLOBENT), w(E8, BLOBENT + 4)
    assert w(E2, BLOBENT) == bmsf, "blob item not in the same place"
    blba, bsec = lba_of(bmsf), (bsz + 2047) // 2048
    exe_secs = set(range(la, la + (sz + 2047) // 2048)); blob_secs = set(range(blba, blba + bsec))
    for s in set(ov2.dirty) | set(ov8.dirty):
        if s < n2 and s not in exe_secs and s not in blob_secs:
            assert ov2.read_sector(s) == ov8.read_sector(s), "sector %d differs outside EXE / blob" % s
    words = [(EXE_BASE + i - EXE_HDR, struct.unpack_from("<I", E8, i)[0]) for i in range(EXE_HDR, sz, 4)
             if E2[i:i + 4] != E8[i:i + 4] and not (BOOT8 <= EXE_BASE + i - EXE_HDR < ZEND)]
    chain = [(a, v) for a, v in words if v == _j(BOOT8)]; assert len(chain) == 1, chain
    chain_at = chain[0][0]; assert w(E2, chain_at) == _j(ENTRY), hex(w(E2, chain_at))
    blobw = [(a, v) for a, v in words if a != chain_at and a not in (BLOBENT, BLOBENT + 4)]
    new_lba = n8
    blobw += [(BLOBENT, msf_word(new_lba)), (BLOBENT + 4, bsz)]
    log("dual8: blob %d B at lba %d -> appended at %d; 8 MB-only EXE words %s" % (
        bsz, blba, new_lba, ", ".join("%08x=%08x" % (a, v) for a, v in blobw)))
    assert E2[off(BOOT8):off(ZEND)] == bytes(ZEND - BOOT8), "2 MB boot area not zero"
    boot8 = bytearray(E8[off(BOOT8):off(DUAL)])
    assert E8[off(DUAL):off(ZEND)] == bytes(ZEND - DUAL), "8 MB build uses the DUAL area"
    ex = [i for i in range(0, len(boot8) - 8, 4)
          if struct.unpack_from("<3I", boot8, i) == (0x3C080000 | ENTRY >> 16, 0x35080000 | ENTRY & 0xFFFF, 0x01000008)]
    assert len(ex) == 1, ex
    struct.pack_into("<2I", boot8, ex[0], 0x3C080000 | WIPE_AT >> 16, 0x35080000 | WIPE_AT & 0xFFFF)
    wa = Asm(WIPE_AT)
    wa.lui("$t0", BOOT8 >> 16); wa.ori("$t0", "$t0", BOOT8 & 0xFFFF)
    wa.lui("$t1", ZEND >> 16); wa.ori("$t1", "$t1", ZEND & 0xFFFF)
    wa.label("wl"); wa.sw("$zero", 0, "$t0"); wa.addiu("$t0", "$t0", 4); wa.bne("$t0", "$t1", "wl"); wa.nop()
    wa.word(_j(ENTRY)); wa.nop()
    wipe = wa.assemble()
    a = Asm(DUAL)
    def li(r, v): a.lui(r, v >> 16 & 0xFFFF); a.ori(r, r, v & 0xFFFF)
    li("$t0", 0x80085800); li("$t2", 0x80685800)
    a.lw("$t1", 0xac, "$t0"); a.nop()
    a.word(0x01205827)
    a.sw("$t3", 0xac, "$t2"); a.lw("$t5", 0xac, "$t0"); a.lw("$t4", 0xac, "$t2"); a.nop()
    a.bne("$t4", "$t3", "no2"); a.nop()
    a.bne("$t5", "$t1", "no2"); a.nop()
    a.lui("$t6", 0x5a5a); a.ori("$t6", "$t6", 0xa5a5); a.word(0x01cb7026)
    a.sw("$t6", 0xac, "$t2"); a.lw("$t5", 0xac, "$t0"); a.lw("$t4", 0xac, "$t2"); a.nop()
    a.bne("$t4", "$t6", "no2"); a.nop()
    a.bne("$t5", "$t1", "no2"); a.nop()
    for adr, v in blobw:
        li("$t7", adr); li("$t8", v); a.sw("$t8", 0, "$t7")
    a.label("no2")
    a.sw("$t1", 0xac, "$t0")
    li("$t0", DUAL + 0x300); li("$t1", WIPE_AT); a.addiu("$t2", "$zero", len(wipe) // 4)
    a.label("cp"); a.lw("$t3", 0, "$t0"); a.addiu("$t0", "$t0", 4); a.addiu("$t2", "$t2", -1); a.sw("$t3", 0, "$t1")
    a.bne("$t2", "$zero", "cp"); a.addiu("$t1", "$t1", 4)
    a.word(_j(BOOT8)); a.nop()
    dual = a.assemble()
    assert len(dual) <= 0x300 and DUAL + 0x300 + len(wipe) <= ZEND
    E = E2
    E[off(BOOT8):off(BOOT8) + len(boot8)] = boot8
    E[off(DUAL):off(DUAL) + len(dual)] = dual
    E[off(DUAL + 0x300):off(DUAL + 0x300) + len(wipe)] = wipe
    struct.pack_into("<I", E, off(chain_at), _j(DUAL))
    # ---- output overlay ----
    out = cdrom.Overlay(ov2.src_path)
    out.dirty = dict(ov2.dirty); out.nsec = max(ov2.nsec, out.src_sectors)
    for s in range(n2, n8):                               # 8 MB items: the same sectors as in ov8
        out.dirty[s] = bytearray(ov8.read_sector(s))
    out.nsec = max(out.nsec, n8)
    rows = []
    for k in range(bsec):                                  # the 8 MB blob, re-addressed
        s = bytearray(ov8.read_sector(blba + k)); l = new_lba + k + 150
        s[12:15] = bytes([_bcd(l // 4500), _bcd(l // 75 % 60), _bcd(l % 75)]); rows.append(s)
    A = np.frombuffer(b"".join(rows), np.uint8).reshape(-1, SECTOR).copy(); cdrom.seal(A)
    for k in range(bsec): out.dirty[new_lba + k] = bytearray(A[k].tobytes())
    out.nsec = max(out.nsec, new_lba + bsec)
    rows = []; ks = []
    for k in range((sz + 2047) // 2048):
        if E[k * 2048:(k + 1) * 2048] == E2[k * 2048:(k + 1) * 2048] and False: continue
        s = bytearray(out.read_sector(la + k)); s[24:24 + 2048] = bytes(E[k * 2048:(k + 1) * 2048]).ljust(2048, b"\0")
        rows.append(s); ks.append(k)
    A = np.frombuffer(b"".join(rows), np.uint8).reshape(-1, SECTOR).copy(); cdrom.seal(A)
    for i, k in enumerate(ks): out.dirty[la + k] = bytearray(A[i].tobytes())
    log("dual8: %d sectors (2 MB %d, 8 MB %d + blob %d)" % (out.nsec, n2, n8, bsec))
    return out
