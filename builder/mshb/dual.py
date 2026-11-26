"""MSHvSF 8 MB "dual" image from the builder's two overlays (user rule 2026-11-24: an 8 MB disc in 2 MB mode must behave
exactly like the 2 MB disc).  Same rules as games/mshvsf/tools/ap8/dualm.py (which made the 1.1 final mshvsf_ap8_f11
from m11_f8 + mshvsf_ap8_f10), on cdrom.Overlay objects so the command line and the browser share it:

    compose(ov2, ov8, sym8) -> Overlay
ov2 = the 2 MB build, ov8 = the 8 MB build with the same options, sym8 = the 8 MB build's link symbols (snd_dir, blob_end).
OUT = ov2's image (sectors 0..n2-1) + ov8's sectors [L0 = DMY.DAT start, n8) appended (delta = n2 - L0, MSF fields of the
blob's position tables + the blob's zero-sum word re-fixed) + ov8's OPDEMO.BIN / OPE.ARC; EXE boot chain (header pc0 ->
DUAL in a zero area): open-bus-proof 8 MB test; 8 MB only: ov8's EXE words, the blob entry and the two file-table entries;
WIPE (0x801ff800) clears the area and jumps to the old pc0."""
import struct
import numpy as np
from xvb import cdrom

SECTOR = cdrom.SECTOR
EXE_BASE, EXE_HDR = 0x80010000, 0x800
BLOBENT, FTAB, ARENA = 0x800136c8, 0x800247dc, 0x80087e10
ZA, ZN, WIPE_AT = 0x8001d2a0, 4096, 0x801ff800


class _Dov(cdrom.Disc):
    def __init__(self, ov): self.f = cdrom.OverlayFile(ov)


def _j(t): return 0x08000000 | (t >> 2 & 0x3FFFFFF)
def _bcd(x): return (x // 10) << 4 | x % 10
def msf_word(lba):
    l = lba + 150
    return _bcd(l // 4500) | _bcd(l // 75 % 60) << 8 | _bcd(l % 75) << 16
_ub = lambda b: (b >> 4) * 10 + (b & 15)
def lba_of(w):
    m, s, f, z = w & 0xff, w >> 8 & 0xff, w >> 16 & 0xff, w >> 24
    if z or any((x & 15) > 9 or (x >> 4) > 9 for x in (m, s, f)) or _ub(s) > 59 or _ub(f) > 74: return None
    return _ub(m) * 4500 + _ub(s) * 75 + _ub(f) - 150


def _asm(pc0, recs):
    """DUAL + WIPE + table words (hand-assembled MIPS, the code of games/mshvsf/tools/ap8/dualm.py)"""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
    from mipsasm import Asm
    TESTW = ZA + ZN - 4
    wa = Asm(WIPE_AT)
    wa.lui("$t0", ZA >> 16); wa.ori("$t0", "$t0", ZA & 0xFFFF)
    wa.lui("$t1", (ZA + ZN) >> 16); wa.ori("$t1", "$t1", (ZA + ZN) & 0xFFFF)
    wa.label("wl"); wa.sw("$zero", 0, "$t0"); wa.addiu("$t0", "$t0", 4); wa.bne("$t0", "$t1", "wl"); wa.nop()
    wa.word(_j(pc0)); wa.nop()
    wipe = wa.assemble()
    a = Asm(ZA)
    def li(r, v): a.lui(r, v >> 16 & 0xFFFF); a.ori(r, r, v & 0xFFFF)
    li("$t0", TESTW); li("$t2", TESTW + 0x600000)
    a.lw("$t1", 0, "$t0"); a.nop()
    a.word(0x01205827)
    a.sw("$t3", 0, "$t2"); a.lw("$t5", 0, "$t0"); a.lw("$t4", 0, "$t2"); a.nop()
    a.bne("$t4", "$t3", "no2"); a.nop()
    a.bne("$t5", "$t1", "no2"); a.nop()
    a.lui("$t6", 0x5a5a); a.ori("$t6", "$t6", 0xa5a5); a.word(0x01cb7026)
    a.sw("$t6", 0, "$t2"); a.lw("$t5", 0, "$t0"); a.lw("$t4", 0, "$t2"); a.nop()
    a.bne("$t4", "$t6", "no2"); a.nop()
    a.bne("$t5", "$t1", "no2"); a.nop()
    TAB = ZA + 0x200
    li("$t0", TAB)
    a.label("rec"); a.lw("$t1", 0, "$t0"); a.lw("$t2", 4, "$t0"); a.addiu("$t0", "$t0", 8)
    a.beq("$t1", "$zero", "no2"); a.nop()
    a.label("cpw"); a.lw("$t3", 0, "$t0"); a.addiu("$t0", "$t0", 4); a.addiu("$t2", "$t2", -1); a.sw("$t3", 0, "$t1")
    a.bne("$t2", "$zero", "cpw"); a.addiu("$t1", "$t1", 4)
    a.b("rec"); a.nop()
    a.label("no2")
    li("$t0", TESTW); a.sw("$zero", 0, "$t0")
    WIMG = ZA + 0x180
    li("$t0", WIMG); li("$t1", WIPE_AT); a.addiu("$t2", "$zero", len(wipe) // 4)
    a.label("cp"); a.lw("$t3", 0, "$t0"); a.addiu("$t0", "$t0", 4); a.addiu("$t2", "$t2", -1); a.sw("$t3", 0, "$t1")
    a.bne("$t2", "$zero", "cp"); a.addiu("$t1", "$t1", 4)
    a.word(_j(WIPE_AT)); a.nop()
    dual = a.assemble()
    assert len(dual) <= 0x180 and len(wipe) <= 0x80
    tab = bytearray()
    for adr, d in recs: tab += struct.pack("<2I", adr, len(d) // 4) + d
    tab += bytes(8)
    assert TAB + len(tab) <= TESTW, "table too big"
    return [(ZA, dual), (WIMG, wipe), (TAB, bytes(tab))]


def compose(ov2, ov8, sym8, log=print):
    D2, D8 = _Dov(ov2), _Dov(ov8)
    n2, n8 = ov2.nsec, ov8.nsec
    fa = {n.split("/")[-1]: (l, s) for n, l, s in D2.walk()}
    fb = {n.split("/")[-1]: (l, s) for n, l, s in D8.walk()}
    assert fa == fb, "ISO directories differ"
    la, sz = fa["SLUS_007.93"]; E2 = bytearray(D2.read(la, sz)); E8 = D8.read(la, sz)
    L0 = fa["DMY.DAT"][0]; delta = n2 - L0
    off = lambda x: x - EXE_BASE + EXE_HDR
    w = lambda E, x: struct.unpack_from("<I", E, off(x))[0]
    pc0 = struct.unpack_from("<I", E2, 0x10)[0]; assert pc0 == struct.unpack_from("<I", E8, 0x10)[0]
    own = set(range(la, la + (sz + 2047) // 2048)); alt = {}
    for nm in ("OPDEMO.BIN", "OPE.ARC"):
        l, s = fa[nm]; own |= set(range(l, l + (s + 2047) // 2048)); alt[nm] = (l, s)
    for s in set(ov2.dirty) | set(ov8.dirty):              # below L0 only EXE / OPDEMO / OPE may differ
        if s < L0 and s not in own: assert ov2.read_sector(s) == ov8.read_sector(s), "sector %d differs below L0" % s
    for i in range(0x130):
        for E in (E2, E8):
            l = lba_of(w(E, FTAB + 8 * i)); assert l is None or l < L0, "FTAB entry %x into the region" % i
    assert E2[off(ZA):off(ZA) + ZN] == bytes(ZN) and E8[off(ZA):off(ZA) + ZN] == bytes(ZN), "DUAL area not zero"
    recs = []; i = EXE_HDR
    while i < sz:
        if E2[i:i + 4] != E8[i:i + 4]:
            k = i
            while k < sz and E2[k:k + 4] != E8[k:k + 4]: k += 4
            x = EXE_BASE + i - EXE_HDR
            assert not (ZA <= x < ZA + ZN) and x != BLOBENT, hex(x)
            for q in range(i, k, 4):
                ll = lba_of(struct.unpack_from("<I", E8, q)[0]); assert ll is None or ll < L0 or ll >= n8, hex(EXE_BASE + q - EXE_HDR)
            recs.append((x, bytes(E8[i:k]))); i = k
        else: i += 4
    bmsf, bsz = w(E8, BLOBENT), w(E8, BLOBENT + 4)
    assert lba_of(bmsf) == L0, "8 MB blob not at DMY start"
    recs.append((BLOBENT, struct.pack("<2I", msf_word(L0 + delta), bsz)))
    tail = n2 + (n8 - L0); newpos = {}
    for nm in ("OPDEMO.BIN", "OPE.ARC"):
        l, s = alt[nm]; newpos[nm] = tail; tail += (s + 2047) // 2048
        fi = [k for k in range(0x130) if w(E2, FTAB + 8 * k) == msf_word(l)]; assert len(fi) == 1, (nm, fi)
        recs.append((FTAB + 8 * fi[0], struct.pack("<2I", msf_word(newpos[nm]), s)))
    for x, d in _asm(pc0, recs): E2[off(x):off(x) + len(d)] = d
    struct.pack_into("<I", E2, 0x10, ZA)
    # 8 MB blob: position tables relocated, zero-sum word re-fixed
    blob = bytearray(D8.read(L0, bsz))
    assert sum(struct.unpack("<%dI" % (bsz // 4), bytes(blob))) & 0xFFFFFFFF == 0, "8 MB blob sum"
    lo, hi = sym8["snd_dir"] - ARENA, sym8["blob_end"] - ARENA
    W = np.frombuffer(bytes(blob[lo:hi]), "<u4").copy(); nrel = 0
    for q in range(len(W)):
        ll = lba_of(int(W[q]))
        if ll is not None and L0 <= ll < n8: W[q] = msf_word(ll + delta); nrel += 1
    blob[lo:hi] = W.tobytes()
    struct.pack_into("<I", blob, bsz - 4, -sum(struct.unpack("<%dI" % (bsz // 4 - 1), bytes(blob[:bsz - 4]))) & 0xFFFFFFFF)
    log("dual: L0 %d n2 %d n8 %d delta %d, %d EXE records, %d blob words relocated" % (L0, n2, n8, delta, len(recs), nrel))
    # ---- the output overlay: ov2 + appended sectors + EXE ----
    out = cdrom.Overlay(ov2.src_path)
    out.dirty = dict(ov2.dirty); out.nsec = max(ov2.nsec, out.src_sectors)
    def put(src_lba, dst_lba, n, data=None):
        rows = []
        for k in range(n):
            s = bytearray(ov8.read_sector(src_lba + k))
            if data is not None and k * 2048 < len(data): s[24:24 + 2048] = data[k * 2048:(k + 1) * 2048].ljust(2048, b"\0")
            l = dst_lba + k + 150; s[12:15] = bytes([_bcd(l // 4500), _bcd(l // 75 % 60), _bcd(l % 75)])
            rows.append(s)
        a = np.frombuffer(b"".join(rows), np.uint8).reshape(-1, SECTOR).copy()
        assert (a[:, 15] == 2).all() and not (a[:, 18] & 0x20).any(), "not mode 2 form 1"
        cdrom.seal(a)
        for k in range(n): out.dirty[dst_lba + k] = bytearray(a[k].tobytes())
        out.nsec = max(out.nsec, dst_lba + n)
    bsec = (bsz + 2047) // 2048
    first = bytearray(D8.read(L0, bsec * 2048)); first[:bsz] = blob
    put(L0, n2, bsec, bytes(first))
    for s0 in range(L0 + bsec, n8, 4096):
        put(s0, n2 + (s0 - L0), min(4096, n8 - s0))
    for nm in ("OPDEMO.BIN", "OPE.ARC"):
        l, s = alt[nm]; put(l, newpos[nm], (s + 2047) // 2048)
    rows = []
    for k in range((sz + 2047) // 2048):
        s = bytearray(out.read_sector(la + k)); s[24:24 + 2048] = bytes(E2[k * 2048:(k + 1) * 2048]).ljust(2048, b"\0"); rows.append(s)
    a = np.frombuffer(b"".join(rows), np.uint8).reshape(-1, SECTOR).copy(); cdrom.seal(a)
    for k in range(len(rows)): out.dirty[la + k] = bytearray(a[k].tobytes())
    return out
