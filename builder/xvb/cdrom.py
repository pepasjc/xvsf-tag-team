"""CD-ROM image plumbing: MODE2/2352 sectors, ISO9660 walk, EDC/ECC, and the copy-on-write image.

The build never holds a whole image in memory.  The patched image is described as
    the original image  +  a dictionary {sector number: 2352 new bytes}  (+ sectors appended at the end)
(Overlay).  The command line streams that into the output file; the browser patcher turns it into a
Blob made of slices of the user's file and the new sectors.
"""
import hashlib, io, os, struct
import numpy as np

SECTOR = 2352
# Buffer size for reading the input image.  In the browser every read that reaches the file system is a
# synchronous FileReader round trip (about a millisecond), and the disc tools read sector by sector and
# even byte by byte; a large read-ahead buffer turns ~50,000 of those into a few hundred.
READ_AHEAD = 1 << 21

# ---------------------------------------------------------------- EDC / ECC (mode 2 form 1), vectorised over sectors
_edc_lut = np.zeros(256, np.uint32)
for _i in range(256):
    _e = _i
    for _ in range(8): _e = (_e >> 1) ^ (0xD8018001 if _e & 1 else 0)
    _edc_lut[_i] = _e
_ecc_f = np.zeros(256, np.uint8); _ecc_b = np.zeros(256, np.uint8)
for _i in range(256):
    _j = ((_i << 1) ^ (0x11D if _i & 0x80 else 0)) & 0xFF
    _ecc_f[_i] = _j; _ecc_b[_i ^ _j] = _i


def _ecc_index(major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    idx = np.zeros((minor_count, major_count), np.int64)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        for m in range(minor_count):
            idx[m, major] = index
            index += minor_inc
            if index >= size: index -= size
    return idx


_P_IDX = _ecc_index(86, 24, 2, 86); _Q_IDX = _ecc_index(52, 43, 86, 88)


def _ecc(body, idx):
    """body[N, len] uint8 -> parity [N, 2 * major_count]"""
    n = body.shape[0]; mc = idx.shape[1]
    a = np.zeros((n, mc), np.uint8); b = np.zeros((n, mc), np.uint8)
    for m in range(idx.shape[0]):
        t = body[:, idx[m]]
        a ^= t; b ^= t
        a = _ecc_f[a]
    a = _ecc_b[_ecc_f[a] ^ b]
    return np.concatenate([a, a ^ b], axis=1)


def seal(secs):
    """secs: uint8 [N, 2352], mode 2 form 1 sectors; recomputes EDC and ECC P/Q in place"""
    if not len(secs): return
    e = np.zeros(len(secs), np.uint32)
    for i in range(16, 2072):
        e = (e >> 8) ^ _edc_lut[(e ^ secs[:, i]) & 0xFF]
    secs[:, 2072:2076] = e.astype("<u4").view(np.uint8).reshape(-1, 4)
    body = np.concatenate([np.zeros((len(secs), 4), np.uint8), secs[:, 16:2076]], axis=1)     # header zeroed for mode 2
    p = _ecc(body, _P_IDX)
    secs[:, 2076:2248] = p
    secs[:, 2248:2352] = _ecc(np.concatenate([body, p], axis=1), _Q_IDX)


# A sector that a tool "sealed" (fix_sector) gets this pattern in its EDC/ECC area instead; Overlay.seal_marked()
# computes the real codes for all of them in one vectorised pass at the end.
SEAL_MARK = (hashlib.sha256(b"xvb deferred EDC/ECC").digest() * 9)[:280]


def mark_for_seal(sec):
    """drop-in for tools/mkdisc.py fix_sector(sec): defer the EDC/ECC computation"""
    sec[2072:2352] = SEAL_MARK


# ---------------------------------------------------------------- the copy-on-write image
class Overlay:
    def __init__(self, src_path):
        self.src_path = src_path
        self.src = open(src_path, "rb", buffering=READ_AHEAD)
        self.src.seek(0, 2); size = self.src.tell()
        assert size % SECTOR == 0, "image size is not a multiple of 2352"
        self.src_sectors = size // SECTOR
        self.nsec = self.src_sectors                      # sectors of the patched image
        self.dirty = {}                                   # sector -> bytearray(2352)

    def read_sector(self, s):
        d = self.dirty.get(s)
        if d is not None: return d
        if s >= self.src_sectors: return bytes(SECTOR)
        self.src.seek(s * SECTOR); return self.src.read(SECTOR)

    def sector_for_write(self, s):
        d = self.dirty.get(s)
        if d is None:
            d = self.dirty[s] = bytearray(self.read_sector(s))
            if s >= self.nsec: self.nsec = s + 1
        return d

    def seal_marked(self):
        """EDC/ECC of every sector the tools sealed; -> number of sectors"""
        keys = sorted(s for s, d in self.dirty.items() if d[2072:2352] == SEAL_MARK)
        for i in range(0, len(keys), 4096):
            part = keys[i:i + 4096]
            a = np.frombuffer(b"".join(self.dirty[s] for s in part), np.uint8).reshape(-1, SECTOR).copy()
            assert (a[:, 15] == 2).all() and not (a[:, 18] & 0x20).any(), "sealing a sector that is not mode 2 form 1"
            seal(a)
            for j, s in enumerate(part): self.dirty[s] = bytearray(a[j].tobytes())
        return len(keys)

    def runs(self):
        """the patched image as a list of ("src", first sector, count) | ("new", first sector, bytes)"""
        out = []; pos = 0
        keys = sorted(self.dirty)
        i = 0
        while i < len(keys):
            j = i
            while j + 1 < len(keys) and keys[j + 1] == keys[j] + 1: j += 1
            if keys[i] > pos: out.append(("src", pos, keys[i] - pos))
            out.append(("new", keys[i], b"".join(bytes(self.dirty[s]) for s in keys[i:j + 1])))
            pos = keys[j] + 1; i = j + 1
        if pos < self.nsec:
            assert self.nsec <= self.src_sectors
            out.append(("src", pos, self.nsec - pos))
        return out

    def chunks(self, block=1 << 22):
        """the bytes of the patched image, in order"""
        for kind, first, x in self.runs():
            if kind == "new": yield x
            else:
                self.src.seek(first * SECTOR); left = x * SECTOR
                while left:
                    b = self.src.read(min(block, left)); assert b; left -= len(b); yield b

    def sha1(self):
        h = hashlib.sha1()
        for b in self.chunks(): h.update(b)
        return h.hexdigest()

    def write(self, path):
        h = hashlib.sha1()
        with open(path, "wb") as f:
            for b in self.chunks(): f.write(b); h.update(b)
        return h.hexdigest()


class WholeImage:
    """what OverlayFile.read() returns for "the entire file": a token, not 400 MB of bytes.
    HashShim.sha1() understands it."""
    def __init__(self, ov): self.ov = ov


class OverlayFile(io.RawIOBase):
    """the file object the disc tools get when they open the output image ("rb" / "r+b")"""

    def __init__(self, ov):
        super().__init__(); self.ov = ov; self.pos = 0

    def seek(self, pos, whence=0):
        self.pos = pos if whence == 0 else self.pos + pos if whence == 1 else self.ov.nsec * SECTOR + pos
        return self.pos

    def tell(self): return self.pos
    def readable(self): return True
    def writable(self): return True
    def seekable(self): return True

    def read(self, n=-1):
        end = self.ov.nsec * SECTOR
        if n is None or n < 0:
            if self.pos == 0: self.pos = end; return WholeImage(self.ov)
            n = end - self.pos
        n = max(0, min(n, end - self.pos))
        s, o = divmod(self.pos, SECTOR)
        if o + n <= SECTOR:                               # the common case: inside one sector
            self.pos += n
            return bytes(self.ov.read_sector(s)[o:o + n])
        out = bytearray()
        while n:
            k = min(n, SECTOR - o)
            out += self.ov.read_sector(s)[o:o + k]
            n -= k; s += 1; o = 0
        self.pos += len(out)
        return bytes(out)

    def write(self, data):
        n = len(data); done = 0
        while done < n:
            s, o = divmod(self.pos, SECTOR)
            k = min(n - done, SECTOR - o)
            self.ov.sector_for_write(s)[o:o + k] = data[done:done + k]
            done += k; self.pos += k
        return n


class HashShim:
    """stands in for the hashlib module inside a disc tool: sha1(WholeImage) streams"""
    def __getattr__(self, name): return getattr(hashlib, name)

    @staticmethod
    def sha1(data=b""):
        if isinstance(data, WholeImage):
            data.ov.seal_marked()                         # the hash of the image as it would be on disk
            h = hashlib.sha1()
            for b in data.ov.chunks(): h.update(b)
            return h
        return hashlib.sha1(data)


# ---------------------------------------------------------------- ISO9660
class Disc:
    def __init__(self, path):
        self.f = open(path, "rb", buffering=READ_AHEAD)

    def sec(self, lba):
        self.f.seek(lba * SECTOR + 24); return self.f.read(2048)

    def read(self, lba, size):
        nsec = (size + 2047) // 2048
        self.f.seek(lba * SECTOR)
        raw = np.frombuffer(self.f.read(nsec * SECTOR), np.uint8).reshape(-1, SECTOR)
        return raw[:, 24:24 + 2048].tobytes()[:size]

    def walk(self, lba=None, ln=None, path=""):
        if lba is None:
            rec = self.sec(16)[156:190]
            lba, = struct.unpack_from("<I", rec, 2); ln, = struct.unpack_from("<I", rec, 10)
        for si in range((ln + 2047) // 2048):
            s = self.sec(lba + si); i = 0
            while i < 2048 and s[i]:
                l = s[i]
                e_lba, = struct.unpack_from("<I", s, i + 2); e_sz, = struct.unpack_from("<I", s, i + 10)
                nm = s[i + 33:i + 33 + s[i + 32]].decode("ascii", "replace").split(";")[0]
                if nm not in ("\x00", "\x01"):
                    if s[i + 25] & 2: yield from self.walk(e_lba, e_sz, path + nm + "/")
                    else: yield path + nm, e_lba, e_sz
                i += l


def extract(image, outdir, max_size=8 << 20):
    """every plain file of the disc up to max_size -> outdir/...; -> {path: [lba, size]} of ALL files"""
    d = Disc(image); lmap = {}
    for full, lba, sz in d.walk():
        lmap[full] = [lba, sz]
        if sz <= max_size:
            dst = os.path.join(outdir, *full.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f: f.write(d.read(lba, sz))
    return lmap
