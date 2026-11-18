"""Game words in our blobs are stored as references to the user's own disc, not as bytes.

Where a rewritten routine keeps or moves some of the game's original instructions, the code we generate contains
those words.  builder/data/blobs must not carry them, so every blob stores each such run as a reference
("copy N bytes from file F at offset O"), and the builder fills it in from the files it has just extracted from
the user's disc image (which was checked by SHA-1 before).

Encoded form of a bytes value inside a blob (pipeline._enc / _dec):

    {"__bytes__": "<hex>"}                               no game words in it
    {"__bref__": [seg, ...]}                             seg = "<hex>" (our bytes) or [file, offset, count]

file is the path inside the disc ("SLUS_006.27", "P/P4/STAGE3.BIN"), offset/count in bytes.

Words of the game: two consecutive words (8 bytes, at any byte offset of our data) equal to two words at a
4-byte-aligned offset of a file of the original disc.  Trivial words: 0x00000000 (nop), 0xffffffff, 0x03e00008
(jr ra) and the small integers 1..0xff.

  * the RULE (what work/release12/optA_scan.py checks against every file of the original disc): no stored literal
    contains such a pair in which BOTH words are non-trivial (a nop or jr ra next to one instruction is one
    instruction, not a run);
  * the encoder (record time, encode()) is stricter: it starts a reference at every such pair unless BOTH words are
    trivial (so "nop; lbu" is referenced too), and extends it byte by byte as far as the data agree.  References
    may point to any file of the disc (the builder reads files over 8 MB from the image itself).
"""
import os
import numpy as np

TRIVIAL = frozenset((0x00000000, 0xFFFFFFFF, 0x03E00008))      # nop / 0 (padding), all ones, jr ra
SMALL = 0x100                                                    # and small integers 1..0xff (no instruction; 8 bits of data)
MAX_CAND = 32                                                    # file positions kept per 8-byte window


def _windows(b):
    """u64 value of the 8 bytes at every byte offset of b (little endian) -> array of len(b) - 7"""
    a = np.frombuffer(bytes(b), np.uint8).astype(np.uint64)
    n = len(a) - 7
    if n <= 0: return np.zeros(0, np.uint64)
    w = np.zeros(n, np.uint64)
    for k in range(8): w |= a[k:k + n] << np.uint64(8 * k)
    return w


def _trivial_word(w):
    return w in TRIVIAL or w < SMALL


def _trivial(v):
    """encoder: no reference starts here (both words trivial)"""
    v = int(v)
    return _trivial_word(v & 0xFFFFFFFF) and _trivial_word(v >> 32)


def _counted(v):
    """the rule: a pair of two non-trivial words"""
    v = int(v)
    return not _trivial_word(v & 0xFFFFFFFF) and not _trivial_word(v >> 32)


class Corpus:
    """the files references may point to: {name: bytes}; EXE first (preferred source)"""

    def __init__(self, files, first=(), cache_all=False):
        self.files = dict(files); self.cache_all = cache_all
        self.order = [n for n in first if n in self.files] + sorted(n for n in self.files if n not in first)
        self._aligned = {}

    @classmethod
    def from_dir(cls, root, first=()):
        files = {}
        for d, sub, fs in os.walk(root):
            sub.sort()
            for f in sorted(fs):
                p = os.path.join(d, f)
                files[os.path.relpath(p, root).replace(os.sep, "/")] = open(p, "rb").read()
        return cls(files, first)

    def aligned(self, name):
        if name in self._aligned: return self._aligned[name]
        d = self.files[name]; n = len(d) // 4
        a = np.frombuffer(d[:4 * n], "<u4").astype(np.uint64)
        w = (a[:-1] | (a[1:] << np.uint64(32))) if n >= 2 else np.zeros(0, np.uint64)
        if self.cache_all or len(d) <= 16 << 20: self._aligned[name] = w      # (the scan: big files are not kept)
        return w

    def find(self, values):
        """values (u64 array) -> {value: [(file, byte offset), ...]} for every aligned occurrence (capped)"""
        q = np.unique(np.asarray(values, np.uint64))
        out = {}
        if not len(q): return out
        for name in self.order:
            w = self.aligned(name)
            if not len(w): continue
            pos = np.searchsorted(q, w); pos[pos >= len(q)] = 0
            hit = np.nonzero(q[pos] == w)[0]
            for i in hit.tolist():
                lst = out.setdefault(int(w[i]), [])
                if len(lst) < MAX_CAND: lst.append((name, 4 * i))
        return out


def encode(data, corpus):
    """bytes -> list of segments (hex str | [file, offset, count]); resolve(encode(d)) == d"""
    data = bytes(data)
    w = _windows(data)
    keep = np.array([not _trivial(v) for v in w.tolist()], bool) if len(w) else np.zeros(0, bool)
    hits = corpus.find(w[keep]) if keep.any() else {}
    segs, lit, p, n = [], bytearray(), 0, len(data)
    while p < n:
        best = None
        if p + 8 <= n and keep[p]:
            for name, o in hits.get(int(w[p]), ()):
                f = corpus.files[name]; k = 8
                while p + k < n and o + k < len(f) and data[p + k] == f[o + k]: k += 1
                if best is None or k > best[2]: best = (name, o, k)
        if best is None:
            lit.append(data[p]); p += 1; continue
        if lit: segs.append(lit.hex()); lit = bytearray()
        segs.append(list(best)); p += best[2]
    if lit: segs.append(lit.hex())
    assert resolve(segs, lambda nm, o, k: corpus.files[nm][o:o + k]) == data
    return segs


def resolve(segs, read):
    """segments -> bytes; read(file, offset, count) gives the user's own bytes"""
    out = bytearray()
    for s in segs:
        if isinstance(s, str): out += bytes.fromhex(s)
        else:
            b = read(s[0], s[1], s[2])
            if len(b) != s[2]: raise ValueError("%s: %d bytes at %d not available" % (s[0], s[2], s[1]))
            out += b
    return bytes(out)


def literal_runs(data, corpus, strict=False):
    """the scan: positions in data where 8 bytes equal two words at an aligned offset of a corpus file and the pair
    counts by the rule (strict: by the encoder's test) -> [(offset, file, file offset)]"""
    w = _windows(data)
    if not len(w): return []
    keep = np.array([(not _trivial(v)) if strict else _counted(v) for v in w.tolist()], bool)
    hits = corpus.find(w[keep]) if keep.any() else {}
    return [(p, ) + hits[int(w[p])][0] for p in range(len(w)) if keep[p] and int(w[p]) in hits]
