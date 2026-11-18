"""MSHvSF .DSP character sprite files (kind 6), as much of them as the sprite encoders need
(full model and format notes: common/dsp/dsp.py, games/mshvsf/docs/DSP.md).

  +0   u32 kind (6)       +4 u32 off[4] section offsets (off[0] = 0x14)
  sec0 pixels             per-tile byte RLE streams of 4bpp packed pixel bytes
  sec1 groups             frames (copied)
  sec2 tile table         u32 per tile: bits 0-21 offset into sec0, bit 23 flag, bits 24-27 bytes/8 - 1,
                          bits 28-31 rows/16 - 1
  sec3 animation data     (copied)
"""
import json, struct
import numpy as np
from . import kernels as K


class DSP:
    def __init__(self, data):
        self.d = d = bytes(data)
        self.kind = struct.unpack_from("<I", d, 0)[0]
        assert self.kind == 6, "kind %d: only MSHvSF character files (kind 6)" % self.kind
        self.offs = list(struct.unpack_from("<4I", d, 4))
        assert self.offs[0] == 0x14
        o = self.offs + [len(d)]
        self.sec = [d[o[i]:o[i + 1]] for i in range(4)]
        self.sizes = [len(s) for s in self.sec]
        nt = len(self.sec[2]) // 4
        self.word = np.frombuffer(self.sec[2][:4 * nt], "<u4").astype(np.int64)
        self.n = nt
        self.off = (self.word & 0x3FFFFF).astype(np.int32)
        self.wb = ((((self.word >> 24) & 15) + 1) * 8).astype(np.int32)        # bytes per row
        self.h = (((self.word >> 28) + 1) * 16).astype(np.int32)
        self.nbytes = (self.wb * self.h).astype(np.int32)
        self.buf = None

    def decode_all(self):
        """run the stock decoder model on every tile: self.buf[self.ooff[i]:] = what it writes for tile i
        (self.wlen[i] bytes: the pixels, then the overrun), self.clen[i] = its stream length"""
        if self.buf is None:
            mem = np.frombuffer(self.d + b"\0" * 64, np.uint8)
            self.ooff = np.concatenate([[0], np.cumsum(self.nbytes.astype(np.int64) + 32)]).astype(np.int32)
            buf = np.zeros(int(self.ooff[-1]), np.uint8)
            self.clen = np.zeros(self.n, np.int32); self.wlen = np.zeros(self.n, np.int32)
            K.dsp_rle_all(mem, 0x14, self.off, self.nbytes, buf, self.ooff, self.clen, self.wlen)
            self.buf = buf
            self._b = buf.tobytes()
        return self

    def raw(self, i):
        """the tile's pixel bytes (bytes)"""
        o = int(self.ooff[i]); return self._b[o:o + int(self.nbytes[i])]

    def written(self, i):
        """everything the stock decoder writes for tile i: pixels + overrun (bytes)"""
        o = int(self.ooff[i]); return self._b[o:o + int(self.wlen[i])]


def rle_decode(sec, pos, n):
    """the stock decoder on sec[pos:] -> n bytes (common/dsp/dsp.py rle_decode)"""
    mem = np.frombuffer(bytes(sec) + b"\0" * 64, np.uint8); out = np.zeros(n + 32, np.uint8)
    K.rle_n(mem, pos, n, out)
    return out[:n].tobytes()


def assemble(x, sec0, offs):
    """new file: header, new sec0, sec1, the tile table with the new offsets (flags/size bits kept), sec3
    (common/dsp/dsm.py assemble, kind 6)"""
    offs = np.asarray(offs, np.int64)
    assert (offs < (1 << 22)).all()
    s2 = ((x.word & ~0x3FFFFF) | offs).astype("<u4").tobytes() + x.sec[2][4 * x.n:]
    o1 = 0x14 + len(sec0); o2 = o1 + len(x.sec[1])
    pad1 = (-o2) % 4                                   # keep the u32 tile table aligned
    o2 += pad1; o3 = o2 + len(s2)
    return struct.pack("<5I", x.kind, 0x14, o1, o2, o3) + bytes(sec0) + x.sec[1] + b"\0" * pad1 + s2 + x.sec[3]


def hot_tiles(x, vol, cap):
    """tiles to keep as stock RLE (common/dsp/dsm.py hot_tiles): most decoded bytes per stored RLE byte first,
    until `cap` bytes of RLE streams.  vol = {tile index (str): play volume} (games/mshvsf/work/dsp/hot/<label>.json)
    -> set of tile indices"""
    x.decode_all()
    clen = [int(c) for c in x.clen]; off = [int(o) for o in x.off]
    items = sorted(((v / (clen[int(k)] + 1), int(k)) for k, v in vol.items()), reverse=True)
    sel = set(); used = 0; seen = {}
    for r, k in items:
        key = (off[k], clen[k])
        c = 0 if key in seen else clen[k] + 1
        if used + c > cap: continue
        used += c; seen[key] = 1; sel.add(k)
    for i in range(x.n):                               # every alias of a chosen stream too
        if (off[i], clen[i]) in seen: sel.add(i)
    return sel


def load_hot(path):
    return json.load(open(path))
