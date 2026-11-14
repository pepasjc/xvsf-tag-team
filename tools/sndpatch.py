"""XvSF tag hack 1.2: every character in a battle has its full own sound bank (partners, tagged-in and KO replacement
characters included), on 2 MB and 8 MB machines.  Off with --nosound (the 1.1 image) and with --nospeed (1.0.1).
Notes and test results: work/sound/IMPLEMENT.md.

Stock: XS_MAIN + P1 CHR + P1 partner HELP + P2 CHR + P2 partner HELP, one merged VAB at SPU 0x1010, the SP_EFF2 tile
stash at SPU 0x68000 (work/sound/SPU_MAP.md).  1.2:
  * banks rebuilt at build time from the user's disc (nothing of the game's audio is in the patch):
      XS_MAIN'   without the ROUND n voices 0xb5-0xbb (roundpatch bypasses the banner) and the unplayable 0x91, + 0x112
      CHR+ c     the character's CHR bank without its dead samples (DEAD) + the ids only its HELP bank had (HELPONLY) +
                 ids it requests that no bank of its own had (COPY, Juggernaut's 0x240) + the tag voices (ALIAS, SELALIAS)
    at LEVELS: level 0 lossless (the original ADPCM bytes), levels 1..3 = every sample whose playback rate is above the
    level's cap resampled to it (tools/snd/resample.py, windowed sinc) and re-encoded (tools/snd/adpcm.py, all filters and
    shifts, beam search over nibbles and decoder states), pitch fields raised by the same ratio (1/128 semitone steps).
    Levels 4 / 5 are the 8 MB levels (tools/mkap8disc.py, level8(): + arcade samples / the same capped at 24038 Hz).
  * the sound directory (3 sectors, tools/snd/snd.h) + all level files in DMY.DAT; the battle loader reads the
    directory and picks per battle the best candidate that fits (tools/snd/snddir.c): 2 MB 0x1010..STASH2 (the stash
    moved to the SPU top), 8 MB 0x1010..0x7fff0 (the stash in main RAM at STASH8).
  * EXE: resident code in the quad worker's FREED range (tools/snd/sndres.S), the battle loader's list + bank load
    call, the two file reads of the bank loader 0x8004cb18, the stash upload of the set-0x37 loader, priority bytes of
    the alias ids; cdtile (tools/speed/upload/helpers.S, .if SOUND) fetches tiles from the place the loader recorded.
"""
import os, sys, struct, math, hashlib
from decimal import Decimal, getcontext
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import region

RES, RES_END = 0x80055c34, 0x80055ebc               # tools/speed/quad.py FREED (no reference in the EXE or any disc file)
DIRBUF, DIRSIZE, CODEOFF, ENTOFF = 0x801e0000, 6144, 0x7e0, 0x54
MAGIC = 0x31535658
NB, XSB, NLEV, NOVR = 19, 18, 6, 24
LEVELS = [None, 20000, 17000, 14800]                # 2 MB caps (Hz); levels 4, 5 = 8 MB (tools/mkap8disc.py: level8())
RES8 = 48                                           # sectors kept free in the sound region for the 8 MB level files
L8, LA = 4, 5                                       # 8 MB: lossless + the arcade samples; the same with every sample above
ARCADE_RATE = 24038                                 #  the arcade's 24038 Hz brought down to it (heaviest teams only)
STASH8 = 0x801f0000                                 # 8 MB: SP_EFF2 pixels in main RAM, below the 2 MB loader's limit
TOP = 0x7ea80                                       # SPU 0x7ea80-0x80000: the KO / super finish palettes, written once
                                                    # at boot (0x800f01c0: 0x1580 bytes, base kept at 0x80041dec), read back per finish
# candidates (XS_MAIN level, character level, rank): the lowest rank that fits wins, the most bytes among equal ranks.
# 2 MB: rank = the larger of the two levels (the deepest cut any sample gets), so the cut is as shallow as possible
CAND2 = [(x, c, max(x, c)) for x in range(4) for c in range(4) if abs(x - c) <= 2]
CAND8 = ([(L8, L8, 0), (0, L8, 1), (L8, 0, 1), (0, 0, 2), (L8, LA, 3), (LA, L8, 3), (0, LA, 3), (LA, 0, 3), (LA, LA, 3)]
         + [(0, 1, 4), (1, 0, 4), (1, 1, 4), (1, 2, 5), (2, 1, 5), (2, 2, 5), (3, 3, 6)])
ROUND = list(range(0xb5, 0xbc)) + [0x91]
DEAD = {0x0f: [0x8a], 0x0e: [0x147]}                # Akuma 0x8a (prio 0xff), Bison 0x147 (never requested by Bison;
                                                    # Storm's / Gambit's / Akuma's copies serve the others)
COPY = {0x0f: [(0x154, "CHR09")]}                   # Akuma requests 0x154 (Gou Hadouken etc.): only Ryu's / Ken's banks have it
HELPONLY = {3: [0x16d], 4: [0x125], 6: [0x163], 15: [0x155]}
# per-character ids 0x180 + 0x20 * c + 0x1c..0x1e (tag in / tag out voices: e.g. Sabretooth 0x23c, Juggernaut 0x25d / 0x25e):
# requested by the game, silent on the PS1 (no tone; most also priority 0xff), but their arcade samples are in the
# character's own bank under another id (work/sound/ARCADE_DIFF.md matching): alias tone -> source id, same VAG, no bytes
ALIAS = {0x19c: 0x188, 0x19d: 0x18d, 0x1bc: 0x1a8, 0x1bd: 0x1a6, 0x1be: 0x1a8, 0x1dd: 0x1c7, 0x1de: 0x149, 0x1fc: 0x1e6,
         0x1fd: 0x1eb, 0x1fe: 0x1e7, 0x21c: 0x211, 0x21d: 0x20e, 0x21e: 0x213, 0x23c: 0x22f, 0x23d: 0x227, 0x23e: 0x16f,
         0x25c: 0x24d, 0x25d: 0x24b, 0x25e: 0x24c, 0x27c: 0x26c, 0x27d: 0x26d, 0x27e: 0x26a, 0x2bd: 0x2aa, 0x2dc: 0x2c7,
         0x2dd: 0x2cc, 0x2de: 0x2cd, 0x2fc: 0x2ef, 0x2fd: 0x2eb, 0x2fe: 0x2ee, 0x31c: 0x304, 0x31d: 0x30c, 0x31e: 0x30e,
         0x33c: 0x32c, 0x33d: 0x32a, 0x33e: 0x32d, 0x35d: 0x349, 0x35e: 0x34c, 0x37d: 0x366, 0x37e: 0x365, 0x39c: 0x38a,
         0x39d: 0x389, 0x39e: 0x38a, 0x3bc: 0x3a6, 0x3bd: 0x3ad, 0x3be: 0x3aa}
XSALIAS = {0x112: 0x102}                            # Wolverine's throw requests 0x112 (arcade: the sample of 0x102), prio 0xff
SELALIAS = {0x37c: 0x37a}                           # Akuma 0x37c: its arcade sample is only in SELECT (Akuma's select voice 0x37a)
ALIAS_PRIO = 0x10                                   # the X-Men's (and Ken's) alias ids have priority 0xff: as the SF characters' (0x10)
LIST_TAB = 0x8004f7f0
# EXE words
LIST_AT = 0x8002b044                                # battle loader: bank list + jal 0x8004cb18 (to 0x8002b0a0)
VH_AT, VB_AT = 0x8004cd58, 0x8004cdd0              # bank loader: jal 0x8004ce34 (VH merge), jal 0x8004d418 (VB load)
STASH_AT = 0x800544cc                               # set-0x37 loader: jal 0x80057b40 (SPU upload), then lui/ori 0x68000
_jal = lambda t: struct.pack("<I", 0x0C000000 | (t >> 2 & 0x03FFFFFF))
_j = lambda t: struct.pack("<I", 0x08000000 | (t >> 2 & 0x03FFFFFF))


def enabled():
    return "--nosound" not in sys.argv and "--nospeed" not in sys.argv and region.REGION == "us"


# ------------------------------------------------------------------------------------------------ code (prebaked)
def code(flushcache):
    """-> (resident bytes at RES, its symbols, the directory's code at DIRBUF + CODEOFF)"""
    sys.path.insert(0, os.path.join(HERE, "speed", "upload"))
    import ulib
    defs = dict(FLUSHCACHE=flushcache, DIRBUF=DIRBUF, ENTOFF=ENTOFF, CODEOFF=CODEOFF, MAGIC=MAGIC, DIRSIZE=DIRSIZE)
    res, sym = ulib.gas(os.path.join(HERE, "snd", "sndres.S"), RES, defs)
    assert RES + len(res) <= RES_END, "sndres.S too big: %d > %d" % (len(res), RES_END - RES)
    assert (sym["sndent"] - 0x8003d91c) % 8 == 0
    pub = {k: sym[k] for k in ("snd_list", "vh_w", "vb_w", "stash_up", "stashbase", "snd_on", "snd_xl", "snd_cl", "ap8fn", "sndent")}
    dcode, dsym = ulib.cc(os.path.join(HERE, "snd", "snddir.c"), DIRBUF + CODEOFF,
                          {k: pub[k] for k in ("stashbase", "snd_on", "snd_xl", "snd_cl", "ap8fn")}, extra=["-I" + os.path.join(HERE, "snd")])
    assert dsym["snd_policy"] == DIRBUF + CODEOFF
    return res, pub, dcode


def exe_patches(res, sym, sndent):
    """[(addr, bytes)]: the resident code with the directory's entry, and the hook words"""
    o = sym["sndent"] - RES
    res = res[:o] + sndent + res[o + 8:]
    nop = bytes(4)
    lst = struct.pack("<I", 0x27a40038) + _jal(sym["snd_list"]) + struct.pack("<I", 0x27a50040) + _j(0x8002b0a0) + nop
    out = [(RES, res), (LIST_AT, lst), (VH_AT, _jal(sym["vh_w"])), (VB_AT, _jal(sym["vb_w"])),
           (STASH_AT, _jal(sym["stash_up"])), (STASH_AT + 8, nop + nop)] + prio_patches()
    if os.environ.get("XV_SNDTRACE") == "1":            # developers: sound-request tracer built in (work/sound/impl/trace2.py)
        out += trace_patches()
    return out


TRACE_STUB, TRACE_CNT, TRACE_N = 0x80057d80, 0x80057d7c, 16        # tools/speed/quad.py FREED 0x80057d7c-0x80057f48


def trace_patches():
    """test images only: 0x8004c718 (the play function) -> a stub that logs a0, a1 and two caller words into a 16-entry
    ring at 0x80057e00 (count at 0x80057d7c), then runs the function"""
    from mipsasm import Asm
    a = Asm(TRACE_STUB)
    a.lui("$v1", 0x8005); a.lw("$v0", 0x7d7c, "$v1"); a.nop()
    a.andi("$t9", "$v0", TRACE_N - 1); a.sll("$t9", "$t9", 4); a.addu("$t9", "$t9", "$v1")
    a.sw("$a0", 0x7e00, "$t9"); a.sw("$a1", 0x7e04, "$t9")
    a.lw("$t8", 0x10, "$sp"); a.nop(); a.sw("$t8", 0x7e08, "$t9")
    a.lw("$t8", 0x2c, "$sp"); a.nop(); a.sw("$t8", 0x7e0c, "$t9")
    a.addiu("$v0", "$v0", 1); a.sw("$v0", 0x7d7c, "$v1")
    a.addiu("$sp", "$sp", -0x80)
    a.j(0x8004c718 + 8); a.nop()
    return [(TRACE_CNT, bytes(4) + a.assemble()), (0x8004c718, struct.pack("<I", 0x08000000 | (TRACE_STUB >> 2 & 0x3ffffff)))]


STOCK_WORDS = {LIST_AT: (20, "566a29b24f81a7db892cb085a8707a32ab55fb19"), VH_AT: (4, _jal(0x8004ce34)), VB_AT: (4, _jal(0x8004d418)),     # (bytes, the stock word or
               STASH_AT: (4, _jal(0x80057b40)), STASH_AT + 8: (8, "84ab61309789530d4e650ddc2231f472cb803521")}                   #  the SHA-1 of the stock words)


# ------------------------------------------------------------------------------------------------ banks
def _files():
    return region.FILES


def _bank(name, kind):
    d = {"CHR": "0", "HELP": "1"}.get(name[:4] if name.startswith("HELP") else name[:3], "2")
    vh = open(os.path.join(_files(), "SE", "VH" + d, name + ".VH"), "rb").read()
    vb = open(os.path.join(_files(), "SE", "VB" + d, name + ".VB"), "rb").read()
    from snd import vab
    return vab.Vab(vh, vb)


def exe_lists():
    """the game's static id lists per bank (0x8004f7f0) -> {bank: [ids]}"""
    exe = open(region.EXEPATH, "rb").read()
    u32 = lambda a: struct.unpack_from("<I", exe, a - 0x80010000 + 0x800)[0]
    out = {}
    for b in range(0x29):
        p, l = u32(LIST_TAB + 4 * b), []
        while True:
            v = struct.unpack_from("<H", exe, p - 0x80010000 + 0x800)[0]; p += 2
            if v == 0xffff: break
            l.append(v)
        out[b] = l
    return out


getcontext().prec = 60
_LN2 = Decimal(2).ln()


def _c128(cap):
    """1536 * log2(44100 / cap): the pitch (1/128 semitone) that brings 44100 Hz down to cap, exact decimal"""
    return (Decimal(44100) / Decimal(cap)).ln() / _LN2 * 1536


def _vag_pcm(b):
    from snd import adpcm
    return adpcm.decode(b[16:-16])               # data blocks only (zero head block, filler tail)


def _vag_new(pcm):
    from snd import adpcm
    return adpcm.vag_body(pcm)


def cap_bank(v, cap, log=None, tag=""):
    """resample every VAG of v whose lowest playback rate is above cap; pitch fields follow (exactly)"""
    if cap is None: return v
    from snd import resample
    c = _c128(cap)
    users = {}
    for p, t, x in v.slots(): users.setdefault(x.vag, []).append((p, t, x))
    for g, us in sorted(users.items()):
        need = max(Decimal((t + 12) * 128 - x.pitch128()) + c for p, t, x in us)    # pitch raise that brings each tone <= cap
        d = int(need.to_integral_value(rounding="ROUND_CEILING"))
        if d <= 0: continue
        num, den = resample.pow2_ratio(d)
        pcm = _vag_pcm(v.vags[g])
        out = resample.resample(pcm, num, den)
        v.vags[g] = _vag_new(out)
        for p, t, x in us: x.set_pitch128(x.pitch128() + d)
        if log is not None: log.append((tag, p * 16 + t if len(us) == 1 else [pp * 16 + tt for pp, tt, xx in us], g, d, len(pcm), len(out)))
    return v


def xs_bank():
    v = _bank("XS_MAIN", "XS")
    for sid in ROUND: v.clear(sid)
    for sid, src in sorted(XSALIAS.items()): v.add_alias(sid, src)
    v.drop_unused()
    return v


def chr_bank(c):
    v = _bank("CHR%02X" % c, "CHR")
    for sid in DEAD.get(c, []): v.clear(sid)
    for sid in HELPONLY.get(c, []):
        h = _bank("HELP%02X" % c, "HELP")
        x = h.tone_of(sid)
        v.add_tone(sid, x.raw, h.vags[x.vag], like=h)
    for sid, name in COPY.get(c, []):
        h = _bank(name, "CHR"); x = h.tone_of(sid)
        v.add_tone(sid, x.raw, h.vags[x.vag], like=h)
    for sid, src in sorted(ALIAS.items()):
        if (sid - 0x180) >> 5 == c:
            v.add_alias(sid, src)
    for sid, src in sorted(SELALIAS.items()):
        if (sid - 0x180) >> 5 == c:
            h = _bank("SELECT", "SE"); x = h.tone_of(src)
            v.add_tone(sid, x.raw, h.vags[x.vag], like=h, src=src)
    v.drop_unused()
    return v


def char_ids(c):
    """ids a character's 1.2 bank adds to its id list: HELP-only ids and the alias ids"""
    return (HELPONLY.get(c, []) + [s for s, n in COPY.get(c, [])] + ([0x240] if c == 6 else [])
            + sorted(s for s in list(ALIAS) + list(SELALIAS) if (s - 0x180) >> 5 == c))   # Juggernaut 0x240: his KO scream


def prio_patches():
    """the alias ids with priority 0xff -> ALIAS_PRIO (only heard where a 1.2 bank lists them)"""
    exe = open(region.EXEPATH, "rb").read(); out = []
    for s in sorted(list(ALIAS) + list(SELALIAS) + list(XSALIAS) + list(ARC8)):
        a = 0x8004f894 + s
        if exe[a - 0x80010000 + 0x800] == 0xff: out.append((a, bytes([ALIAS_PRIO])))
    return out


def build_banks(levels=LEVELS, log=None):
    """{(bank, level): (vh, vb)} for bank 0..17 (characters) and XSB (XS_MAIN), levels 0..len(levels)-1"""
    out = {}
    for b in list(range(18)) + [XSB]:
        for k, cap in enumerate(levels):
            v = xs_bank() if b == XSB else chr_bank(b)
            out[(b, k)] = cap_bank(v, cap, log, "XS" if b == XSB else "CHR%02X" % b).build()
    return out


def lists(levels8=None):
    """id-list overrides -> [(bank, levmask, [ids])].  levels8: {bank: [extra ids]} of the 8 MB level"""
    L = exe_lists(); out = []
    lv2 = (1 << len(LEVELS)) - 1
    xs = [i for i in L[0x26] if i not in ROUND] + sorted(XSALIAS)
    ex8 = levels8 or {}
    m8 = 1 << L8 | 1 << LA
    out.append((0x26, lv2 | (0 if 0x26 in ex8 else m8), xs))
    if 0x26 in ex8: out.append((0x26, m8, xs + [i for i in ex8[0x26] if i not in xs]))
    for c in range(18):
        add = char_ids(c)
        base = L[c] + [i for i in add if i not in L[c]]
        if c in ex8:
            out.append((c, lv2, base)); out.append((c, m8, base + [i for i in ex8[c] if i not in base]))
        elif add:
            out.append((c, lv2 | m8, base))
    assert len(out) <= NOVR
    return out


def dir_sector(ent, dcode, ovr, stash2, stash8=STASH8, cand2=CAND2, cand8=CAND8):
    """ent: {(level, bank): (vh entry 8 bytes, vb entry 8 bytes)} -> the 4096-byte sound directory"""
    d = bytearray(DIRSIZE)
    struct.pack_into("<I", d, 0, MAGIC)
    for o, cand in ((0x0c, cand2), (0x2c, cand8)):
        assert len(cand) <= 16
        for i in range(16):
            x, c, r = cand[i] if i < len(cand) else (15, 15, 255)
            struct.pack_into("<H", d, o + 2 * i, r << 8 | x << 4 | c)
    struct.pack_into("<II", d, 0x4c, stash2, stash8)
    for (l, b), (vh, vb) in ent.items():
        o = ENTOFF + (l * NB + b) * 16
        d[o:o + 8] = vh; d[o + 8:o + 16] = vb
    o = ENTOFF + NLEV * NB * 16
    assert o == 0x774 and (DIRBUF + ENTOFF) % 8 == 4
    struct.pack_into("<I", d, o, len(ovr))
    assert CODEOFF >= o + 4 + 4 * NOVR
    d[CODEOFF:CODEOFF + len(dcode)] = dcode
    p = (CODEOFF + len(dcode) + 3) & ~3
    for i, (bank, mask, ids) in enumerate(ovr):
        struct.pack_into("<BBH", d, o + 4 + 4 * i, bank, mask, p)
        lst = struct.pack("<%dH" % (len(ids) + 1), *(ids + [0xffff]))
        d[p:p + len(lst)] = lst; p = (p + len(lst) + 3) & ~3
    assert p <= DIRSIZE, "sound directory overflow: %d" % p
    n = p // 4 - 2                                      # words summed: from nwords (word 2) to the end of the lists
    struct.pack_into("<I", d, 8, n)
    struct.pack_into("<I", d, 4, sum(struct.unpack_from("<%dI" % n, d, 8)) & 0xffffffff)
    return bytes(d)


def stash_size():
    """SP_EFF2's pixel section (what the set-0x37 loader uploads): file size - header word 3"""
    f = open(os.path.join(_files(), "A", "A2", "SP_EFF2.NSP"), "rb").read()
    h = struct.unpack_from("<4I", f)
    return len(f) - h[3]


def stash2():
    n = (stash_size() + 63) & ~63                   # SpuWrite moves whole 64-byte blocks
    return (TOP - n) & ~7


# ------------------------------------------------------------------------------------------------ disc
_CACHE = {}


def _cache_dir():
    from mkdisc import BUILD
    d = os.path.join(BUILD, "snd"); os.makedirs(d, exist_ok=True); return d


def _src_key():
    """identity of the inputs: the disc's sound files and the encoder sources (results are cached in build/snd)"""
    h = hashlib.sha1()
    for d in ("VH0", "VB0", "VH1", "VB1", "VH2", "VB2"):
        p = os.path.join(_files(), "SE", d)
        for f in sorted(os.listdir(p)):
            if f.startswith(("CHR", "HELP", "XS_MAIN")): h.update(f.encode()); h.update(open(os.path.join(p, f), "rb").read())
    for f in ("sndpatch.py", "snd/vab.py", "snd/adpcm.py", "snd/resample.py", "snd/sinc_table.py"):
        h.update(open(os.path.join(HERE, f), "rb").read().replace(b"\r\n", b"\n"))
    h.update(repr(LEVELS).encode())
    return h.hexdigest()[:16]


def banks():
    """{(level, bank): (vh, vb)} of the 2 MB levels (cached in build/snd/<key>.bin)"""
    if "banks" in _CACHE: return _CACHE["banks"]
    key = _src_key(); p = os.path.join(_cache_dir(), key + ".bin")
    out = {}
    if os.path.exists(p):
        d = open(p, "rb").read(); o = 0
        while o < len(d):
            l, b, n1, n2 = struct.unpack_from("<4I", d, o); o += 16
            out[(l, b)] = (d[o:o + n1], d[o + n1:o + n1 + n2]); o += n1 + n2
    else:
        log = []
        raw = build_banks(LEVELS, log)
        out = {(l, b): v for (b, l), v in raw.items()}
        open(p, "wb").write(b"".join(struct.pack("<4I", l, b, len(vh), len(vb)) + vh + vb for (l, b), (vh, vb) in sorted(out.items())))
        open(p[:-4] + "_log.txt", "w").write("".join("%s %s vag %d +%d/128 semitone %d -> %d samples\n" % (t, (hex(s) if isinstance(s, int) else [hex(x) for x in s]), g, dd, a, b2) for t, s, g, dd, a, b2 in log))
    _CACHE["banks"] = out
    return out


def disc_items(level8=None):
    """the files of the sound region in read order: [(key, data, label)] and {(level, bank): (vh key, vb key)}.
    level8: {bank: (vh, vb)} of the 8 MB level (default: level 0 again)"""
    bk = dict(banks())
    for b in range(NB):
        for l in (L8, LA):
            bk[(l, b)] = (level8 or {}).get((l, b), bk[(0, b)])
    items = [(("snddir",), bytes(DIRSIZE), "sound directory (%d sectors)" % (DIRSIZE // 2048))]
    seen = {}; ref = {}
    name = lambda b: "XS_MAIN" if b == XSB else "CHR%02X" % b
    for kind in (0, 1):                                 # all VH files, then all VB files (the bank loader reads them so)
        if kind == 1:                                   # room for the 8 MB build's level files next to the 2 MB ones (a far seek per file else)
            items.append((("snd8res",), bytes(RES8 * 2048), "sound: room for 8 MB level files (%d sectors)" % RES8))
        for l in range(NLEV if level8 is None else L8):
            for b in [XSB] + list(range(18)):
                data = bk[(l, b)][kind]
                h = hashlib.sha1(data).digest()
                if h not in seen:
                    k = ("snd", kind, l, b); seen[h] = k
                    items.append((k, data, "sound %s level %d %s (%d bytes)" % (name(b), l, ("VH", "VB")[kind], len(data))))
                ref.setdefault((l, b), [None, None])[kind] = seen[h]
    return items, ref


# ------------------------------------------------------------------------------------------------ 8 MB levels
ARC8 = {0x19e: (0, 0x19d)}                          # arcade sample id -> (character, id whose tone attributes it takes)


def level8(snd8):
    """the two 8 MB levels from the arcade samples of tools/ap/snd8build.py ({id: (rate, int8 PCM)}):
    -> ({(level, bank): (vh, vb)}, {bank: [extra ids]})"""
    from snd import adpcm, vab
    import numpy as np
    out, extra = {}, {}
    for b in list(range(18)) + [XSB]:
        v = xs_bank() if b == XSB else chr_bank(b)
        for sid, (c, like) in sorted(ARC8.items()):
            if b != c or sid not in snd8: continue
            rate, raw = snd8[sid]
            pcm = (np.frombuffer(raw, dtype=np.int8).astype(np.int32) << 8).astype(np.int16)
            x = v.tone_of(like)
            t = sid & 15
            p128 = int(((t + 12) * 128 + (Decimal(44100) / Decimal(rate)).ln() / _LN2 * 1536).to_integral_value(rounding="ROUND_HALF_EVEN"))
            v.add_tone(sid, x.raw, adpcm.vag_body(pcm))
            v.tone_of(sid).set_pitch128(p128)
            extra.setdefault(b, []).append(sid)
        out[(L8, b)] = v.build()
        out[(LA, b)] = cap_bank(v, ARCADE_RATE).build()
    return out, extra


def msf(lba):
    return bytes(((x // 10) << 4 | x % 10) for x in ((lba + 150) // 4500, (lba + 150) // 75 % 60, (lba + 150) % 75)) + bytes(1)


def dir_data(pos, size, ref, dcode, ovr=None):
    ent = {k: tuple(msf(pos[kk]) + struct.pack("<I", size[kk]) for kk in v) for k, v in ref.items()}
    d = dir_sector(ent, dcode, ovr if ovr is not None else lists(), stash2())
    return d[:DIRSIZE - 8] + msf(pos[("snd8res",)]) + struct.pack("<I", size[("snd8res",)])     # the room (outside the word sum)


def choose(team, is8=False, sizes=None):
    """Python model of snddir.c: team = character ids (any order, -1 none) -> (xs level, character level, bytes).
    sizes: {(level, bank): (vh, vb)} incl. the 8 MB levels (default: banks(), 8 MB levels = level 0)"""
    bk = banks() if sizes is None else sizes
    sz = lambda l, b: len(bk[(l, b) if (l, b) in bk else (0, b)][1])
    lst = []
    for c in team:
        c = 0x0b if c == 0x12 else c
        if c >= 0 and c not in lst: lst.append(c)
    lim = (TOP if is8 else stash2()) - 0x1010
    best = None
    cands = CAND8 if is8 else CAND2
    for x, c, r in cands:
        t = sz(x, XSB) + sum(sz(c, b) for b in lst)
        k = r << 20 | (0xfffff - t)                                  # as snddir.c: rank, then the most bytes
        if t <= lim and (best is None or k < best[0]): best = (k, x, c, t)
    if best is None: x, c, r = cands[-1]; return x, c, sz(x, XSB) + sum(sz(c, b) for b in lst)
    return best[1], best[2], best[3]
