"""The game's sprite file (.NSP), as much of it as the encoders need (full model: tools/nsp.py).

  header  4 x u32 section offsets
  sec0    sprite-part records            (copied)
  sec1    u32 per tile: bits 0-21 offset into sec2, bits 22-23 flags, bits 24-27 bytes wide / 8 - 1,
          bits 28-31 rows / 16 - 1
  sec2    per-tile streams (stock: byte RLE of 4bpp packed pixel bytes)
  sec3    animation / frame tables       (copied)
"""
import struct
import numpy as np
from . import kernels as K


class NSP:
    def __init__(self, data):
        self.d = d = bytes(data)
        self.offs = list(struct.unpack_from("<4I", d, 0))
        o = self.offs + [len(d)]
        self.sec = [d[o[i]:o[i + 1]] for i in range(4)]
        self.word = np.frombuffer(self.sec[1], "<u4").astype(np.int64)
        self.n = len(self.word)
        self.off = (self.word & 0x3FFFFF).astype(np.int32)
        self.wb = ((((self.word >> 24) & 15) + 1) * 8).astype(np.int32)        # bytes per row
        self.h = (((self.word >> 28) + 1) * 16).astype(np.int32)
        self.nbytes = self.wb * self.h
        self.roff = np.concatenate([[0], np.cumsum(self.nbytes)]).astype(np.int32)   # tile i = raw[roff[i]:roff[i+1]]
        self.raw = None; self.clen = None

    def decode_all(self):
        """decode every tile's stock RLE stream -> self.raw (uint8, concatenated), self.clen"""
        if self.raw is None:
            mem = np.frombuffer(self.d + b"\0" * 32, np.uint8)
            raw = np.zeros(int(self.roff[-1]), np.uint8); clen = np.zeros(self.n, np.int32)
            K.rle_decode_all(mem, self.offs[2], self.off, self.nbytes, raw, self.roff, clen)
            self.raw, self.clen = raw, clen
        return self

    def tile(self, i):
        return self.raw[self.roff[i]:self.roff[i + 1]]

    def unique(self, skip=()):
        """tiles with distinct (width, pixels), first occurrence order, without the tiles in `skip`
        -> (list of tile indices, {tile index: position in that list} for every tile not skipped)"""
        skip = set(skip); seen = {}; order = []; where = {}
        rb = self.raw.tobytes()
        for i in range(self.n):
            if i in skip: continue
            k = (int(self.wb[i]), rb[self.roff[i]:self.roff[i + 1]])
            j = seen.get(k)
            if j is None: j = seen[k] = len(order); order.append(i)
            where[i] = j
        return order, where
