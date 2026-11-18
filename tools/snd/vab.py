"""PS1 libsnd VAB banks (VH header + VB body) as the game stores them in SE/VH*/ and SE/VB*/.

VH layout: 32-byte header ('pBAV', version, vab id, fsize = VH + VB bytes, reserved, ps programs, ts tones,
vs VAGs, master vol/pan, attrs, reserved), 128 x 16-byte program attributes (byte 0 = tone count), ps x 16 x
32-byte tone attributes (program k = k-th present program in number order), 256 x u16 VAG sizes (bytes >> 3,
entry 0 unused).  Tone: prior, mode, vol, pan, center, shift (1/128 semitone, added to center), min, max,
vibW, vibT, porW, porT, pbmin, pbmax, res, res, adsr1, adsr2, prog (s16), vag (s16; 0 / 255 = empty slot), 4 res.
VB: the VAG bodies concatenated in VAG number order.

The game keys note = tone index (id & 15) on program id >> 4, so a tone's playback rate is
    44100 * 2 ** ((note + 12 - center - shift / 128) / 12).
"""
import struct, math

EMPTY = (0, 255)
FILLER = bytes([0, 7]) + bytes([0x77]) * 14         # the block every game VAG ends with


class Tone:
    __slots__ = ("raw",)

    def __init__(self, raw):
        self.raw = bytearray(raw)

    center = property(lambda s: s.raw[4], lambda s, v: s.raw.__setitem__(4, v))
    shift = property(lambda s: s.raw[5], lambda s, v: s.raw.__setitem__(5, v))
    mn = property(lambda s: s.raw[6])
    mx = property(lambda s: s.raw[7])

    @property
    def vag(self): return struct.unpack_from("<h", self.raw, 22)[0]

    @vag.setter
    def vag(self, v): struct.pack_into("<h", self.raw, 22, v)

    @property
    def prog(self): return struct.unpack_from("<h", self.raw, 20)[0]

    @prog.setter
    def prog(self, v): struct.pack_into("<h", self.raw, 20, v)

    def empty(self): return self.vag in EMPTY

    def rate(self, note=None):
        n = self.mn if note is None else note
        return 44100 * 2 ** ((n + 12 - self.center - self.shift / 128) / 12)

    def pitch128(self):
        """center + shift in 1/128 semitone"""
        return self.center * 128 + self.shift

    def set_pitch128(self, p):
        assert 0 <= p < 128 * 128
        self.center, self.shift = p >> 7, p & 127


class Vab:
    def __init__(self, vh, vb):
        self.hdr = bytearray(vh[:32])
        assert self.hdr[:4] == b"pBAV"
        self.ps, self.ts, self.vs = struct.unpack_from("<HHH", vh, 0x12)
        self.pattr = [bytearray(vh[0x20 + 16 * i:0x30 + 16 * i]) for i in range(128)]
        present = [i for i in range(128) if self.pattr[i][0]]
        assert len(present) == self.ps, (len(present), self.ps)
        self.tones = {}                                   # program -> [Tone x 16] (all 16 slots kept)
        for k, p in enumerate(present):
            self.tones[p] = [Tone(vh[0x820 + 512 * k + 32 * t:0x820 + 512 * k + 32 * t + 32]) for t in range(16)]
        vo = 0x820 + 512 * self.ps
        sizes = [struct.unpack_from("<H", vh, vo + 2 * i)[0] * 8 for i in range(256)]
        self.vagtab_tail = sizes[self.vs + 1:]            # kept as they are (normally 0)
        self.vags = [None]
        self.short = len(vb) == sum(sizes[1:self.vs + 1]) - 16 and vb[:16] != bytes(16)
        if self.short:                                    # CHR0E/0F/10: the body lacks the first VAG's zero head block
            vb = bytes(16) + vb                           # (the game plays them fine: addresses land on the data blocks)
        o = 0
        for i in range(1, self.vs + 1):
            self.vags.append(bytes(vb[o:o + sizes[i]])); o += sizes[i]
        self.vb_tail = bytes(vb[o:])                      # bytes after the last VAG
        self.vh_tail = bytes(vh[vo + 512:])

    # ---- queries
    def slots(self):
        """[(program, tone index, Tone)] of the non-empty used tone slots (tone index < tone count)"""
        out = []
        for p, tl in sorted(self.tones.items()):
            for t in range(self.pattr[p][0]):
                if not tl[t].empty(): out.append((p, t, tl[t]))
        return out

    def tone_of(self, sid):
        p, t = sid >> 4, sid & 15
        if p not in self.tones or t >= self.pattr[p][0]: return None
        x = self.tones[p][t]
        return None if x.empty() else x

    def users(self, v):
        return [(p, t, x) for p, t, x in self.slots() if x.vag == v]

    # ---- edits
    def clear(self, sid):
        """empty the tone slot of sound id sid (the VAG stays; drop_unused() removes it)"""
        x = self.tone_of(sid)
        if x is not None: x.vag = 255

    def drop_unused(self):
        used = sorted(set(x.vag for p, t, x in self.slots()))
        remap = {v: i + 1 for i, v in enumerate(used)}
        self.vags = [None] + [self.vags[v] for v in used]
        for p, t, x in self.slots(): x.vag = remap[x.vag]
        self.vs = len(self.vags) - 1

    def ensure_program(self, p, ntones, like=None):
        if p not in self.tones:
            src = like.pattr[p] if like is not None else None
            self.pattr[p] = bytearray(src) if src is not None else bytearray(b"\x00\x7f\xff\xff\x40\xff\x00\x00" + b"\xff" * 8)
            self.pattr[p][0] = 0
            self.tones[p] = [Tone(like.tones[p][t].raw if like is not None and p in like.tones else self._blank(p, t)) for t in range(16)]
            for t in range(16):
                self.tones[p][t].vag = 255
            self.ps += 1
        if self.pattr[p][0] < ntones:
            self.pattr[p][0] = ntones

    def _blank(self, p, t):
        r = bytearray(32); r[0] = 0xff; r[2] = 0x7f; r[3] = 0x40; r[4] = 24 + t; r[6] = r[7] = t
        struct.pack_into("<HHhh", r, 16, 0x80ff, 0x5fc6, p, 255)
        return r

    def add_tone(self, sid, tone_raw, vag_bytes, like=None, src=None):
        """put a tone (raw attributes of another bank, of id src: default sid) and its VAG into slot sid"""
        p, t = sid >> 4, sid & 15
        self.ensure_program(p, t + 1, like)
        x = Tone(tone_raw); x.prog = p
        if src is not None: x.set_pitch128(x.pitch128() + 128 * (t - (src & 15)))   # same playback rate in its new slot
        self.vags.append(bytes(vag_bytes)); self.vs = len(self.vags) - 1
        x.vag = self.vs
        self.tones[p][t] = x

    def add_alias(self, sid, src):
        """tone slot sid plays the same VAG with the same attributes as id src (no new sample data)"""
        x = self.tone_of(src)
        assert x is not None, hex(src)
        p, t = sid >> 4, sid & 15
        sp = src >> 4
        if p not in self.tones:
            self.pattr[p] = bytearray(self.pattr[sp]); self.pattr[p][0] = 0
            self.tones[p] = [Tone(self._blank(p, k)) for k in range(16)]
            self.ps += 1
        if self.pattr[p][0] < t + 1: self.pattr[p][0] = t + 1
        y = Tone(x.raw); y.prog = p
        y.set_pitch128(x.pitch128() + 128 * (t - (src & 15)))      # the game keys note = tone index: same playback rate
        self.tones[p][t] = y

    # ---- output
    def build(self):
        vb = b"".join(self.vags[1:]) + self.vb_tail
        ps = len(self.tones)
        vh = bytearray(self.hdr)
        tc = sum(self.pattr[p][0] for p in self.tones)
        struct.pack_into("<HHH", vh, 0x12, ps, self.ts_count(), self.vs)
        for i in range(128): vh += self.pattr[i]
        for p in sorted(self.tones):
            for x in self.tones[p]: vh += x.raw
        sizes = [0] + [len(v) for v in self.vags[1:]]
        assert all(s % 16 == 0 for s in sizes)
        tab = sizes + self.vagtab_tail[:256 - len(sizes)]
        tab += [0] * (256 - len(tab))
        vh += struct.pack("<256H", *[s // 8 for s in tab])
        vh += self.vh_tail
        struct.pack_into("<I", vh, 12, len(vh) + len(vb))
        return bytes(vh), vb

    def ts_count(self):
        """header tone count: the sum of the programs' tone counts (placeholder slots included)"""
        return sum(self.pattr[p][0] for p in self.tones)


def load(vh_path, vb_path):
    return Vab(open(vh_path, "rb").read(), open(vb_path, "rb").read())


def roundtrip_ok(vh, vb):
    v = Vab(vh, vb)
    a, b = v.build()
    return a == vh and (b == vb or (v.short and b == bytes(16) + vb))
