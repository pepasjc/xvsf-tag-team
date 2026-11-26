"""MvC character animation tables (PLxx_10.A0 code section) -> which animations show which sec1 frame group.

Blob (found through the init code's pointer store [0x80079bc0 + 4 * char], same layout as XvSF's work/ap/anim.py):
  u32 off[4] from the blob start: category table, records, frame table, info records
  category table: u16 byte offsets (from its start) of the per-category lists; list = u16 offsets into the records
  records (4 B): w0 = frame index low 8 bits | duration << 8; w1 = info (12 bits) | frame bits 8-10 << 12 | end << 15; after an end record a
                 u32 loop target (offset into the records)
  frame table (4 B): u16 sec1 offset of the frame group, u16 sec3 offset (0xffff = none)

    from animtab import Anim; a = Anim(c); a.anims -> {(cat, idx): [(frame, dur, group), ...]}; a.group_users[g]
"""
import os, sys, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(GAME, "..", "..", "common", "dsp")); sys.path.insert(0, os.path.join(GAME, "tools"))
import dsp as D, reloc as R

TABLE = 0x80079bc0                   # per-character pointer to the animation blob (char index * 4)


def blob_offset(r, c):
    """file offset of the blob: the init code's 'sw rX, lo(TABLE + 4c)(lui)' store of a lui/addiu-built pointer"""
    want = TABLE + 4 * c; A = r.A; reg = {}
    for i in range(7, min(r.n, 7 + 400)):
        w = A[i]; op = w >> 26; rs = (w >> 21) & 31; rt = (w >> 16) & 31; im = w & 0xffff; s = im - 0x10000 if im & 0x8000 else im
        if op == 0x0f: reg[rt] = im << 16
        elif op == 0x09 and rs in reg: reg[rt] = (reg[rs] + s) & 0xffffffff
        elif op == 0x2b and rs in reg and rt in reg and (reg[rs] + s) & 0xffffffff == want:
            return reg[rt] - R.B10
        elif w == 0x03e00008: break
    raise ValueError("no anim blob store for char %x" % c)


class Anim:
    def __init__(self, c, a0=None):
        self.c = c
        r = R.get(c); b = self.b = a0 or r.a
        S = R.sections(b)
        self.dsp = D.DSP(b[S[1][0]:S[1][0] + S[1][1]]); g = self.dsp.groups()
        st = {s: i for i, (s, h, gg) in enumerate(g)}
        B = self.B = blob_offset(r, c)
        h = self.h = struct.unpack_from("<4I", b, B)
        u16 = lambda o: struct.unpack_from("<H", b, o)[0]
        T = B + h[0]; ncat = u16(T) // 2
        cats = [u16(T + 2 * i) for i in range(ncat)]
        ends = sorted(set(cats + [h[1] - h[0]]))
        self.frames = []
        for i in range((h[3] - h[2]) // 4):
            so, s3 = struct.unpack_from("<HH", b, B + h[2] + 4 * i)
            self.frames.append(st.get(so))
        self.anims = {}; self.loops = {}; self.starts = {}
        for k, co in enumerate(cats):
            nxt = min(e for e in ends if e > co); n = (nxt - co) // 2
            for j in range(n):
                off = u16(T + co + 2 * j)
                if off == 0 and j and k: pass         # offset 0 = the first animation (stance); kept as listed
                self.anims[(k, j)] = self.walk(off); self.starts[(k, j)] = off
        self.group_users = collections.defaultdict(set)
        for key, recs in self.anims.items():
            for f, d, gid, info in recs:
                if gid is not None: self.group_users[gid].add(key)
        self.ncat = ncat

    def walk(self, off, limit=300):
        b = self.b; a = self.B + self.h[1] + off; out = []
        while len(out) < limit and a + 4 <= self.B + self.h[2]:
            w0, w1 = struct.unpack_from("<HH", b, a); a += 4
            f = (w0 & 0xff) | (w1 & 0x7000) >> 4         # engine 0x8003c054 (dx worker, 2026-11-18): frame = w0 low byte
            out.append((f, w0 >> 8, self.frames[f] if f < len(self.frames) else None, w1 & 0xfff))   # | w1 bits 12-14 << 8, dur = w0 >> 8
            if w1 & 0x8000: break
        return out


if __name__ == "__main__":
    for a in sys.argv[1:] or ["3"]:
        c = int(a, 16); x = Anim(c)
        bad = sum(1 for v in x.anims.values() for f, d, g, i in v if g is None)
        print("PL%02X blob %05x cats %d anims %d frames %d bad %d groups %d referenced %d" % (
            c, x.B, x.ncat, len(x.anims), len(x.frames), bad, len(x.dsp.groups()), len(x.group_users)))
