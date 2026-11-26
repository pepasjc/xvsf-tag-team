"""Stage simplification ("stagelite", 2026-11-17): smaller stage overlays -> lower tag-loader region start.

The whole DAT/BGnn.ARC is read to 0x8009dfcc; what stays in RAM for the battle is the ARC header + entry 0 (stage
code, init data, BSS: BG-layer SPRT / DR_MODE double buffers, layer structs, tilemaps) + entry 1 (stage sprite set
0xd, RAM part) + the kept part of entry 2 (common set 0xa) + 0x580 B; the GPU primitive pool (capped at 30000 B by
heapcap) starts right after, then the loader region.  Entries 1-5 are found through the ARC header offsets, so
removing bytes from entry 0 moves entries 1-5 down and with them the pool and the region start.

This module rewrites entry 0 with byte ranges CUT out (data / buffers made dead) and relocates every absolute
reference of the stage code (lui/lo pairs, also through `addu` of a lui register) and every pointer word in the
stage's init data that points past a cut.  Optional code patches (in place, stock word checked) make the removed
feature unreachable.  The file keeps its size (zero padded), so the disc layout and the EXE file table stay as they
are.

    python stagelite.py show ST                     refs / relocations of the configured cut of stage ST
    python stagelite.py disc NAME [ST..]            stock disc + stagelite ARCs (A/B tests without the tag loader)
    mktag.py ... --stagelite[=0,8,9]                tag build with the stagelite ARCs (default: every configured stage)

Configured cuts: CUTS below (RAM addresses, [lo, hi)); docs/TAGLOAD.md "Stage simplification".
"""
import os, sys, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.abspath(os.path.join(GAME, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
BASE = 0x8009dfcc
EXE_SPAWN = 0x8006edf0          # EXE u32[10]: per stage, pointer to its stage-object spawn list (16-B records, -1 end)
                                # in the stage's init data (read by 0x800449c4 at battle init)
EXE_PAL = 0x8006ee24            # EXE u32[10]: per stage, pointer to its 5 initial CLUTs (0x80044984 -> 0x8003b5c8)
# Other EXE tables indexed by the stage byte 0x8007bdd9 (checked 2026-11-17, every `lbu .., -0x4227` site): camera
# function pointers 0x80078884 / 0x800788c4 / 0x80078904 (EXE code), camera constants 0x800789dc / 0x800789fc,
# anim offsets relative to the object's +0x60 base 0x80077a80 / 0x80077ab4 / 0x800780f0 / 0x80078140, 0x8009287c
# (0 for every stage), 0x8009296c (stages 1 / 5).  Only the two pointer tables above point into stage data.

# stage -> dict(cuts=[(lo, hi)], patches=[(addr, stock_word, new_word)], note=...)
CUTS = {
    # Stage 0 (bathhouse), NOT enabled (findings 2026-11-17): BG layer "bit 4" (callback 0x800a0e90, mask 4 of the
    # common draw 0x8009f770) is the ceiling-beam strip at the very top, nearly all behind the HUD; `jr ra` at its
    # callback hides it with no other effect (RAM-patch test).  Its buffers cannot be cut by relocation: SPRT C
    # 0x800a8c04 / DR_MODE 0x800aaeec cut -> GPU hang on the first battle frame (their prims are still reached through
    # another layer's chain); the 6 KB tilemap 0x800ae114 cut -> garbage BG (the four tilemaps 0x800ab114.. are one
    # array, base + layer * 0x1800).  The tilemap slot is dead after the callback patch: usable as a loader fragment.
    # Config kept for reference: STAGE0_LAYER3 below.
    # Stage 8 (rocky mountains): time-of-day colour transition.  0x8009e840 (called every frame from the camera
    # update) switches by round timer 0x8007b832: < 61 s camera-struct +6 = 2 and spawns effect object type 0xd8
    # sub 6 (sunset fade), < 31 s +6 = 4, sub 7 (night).  Type 0xd8 = EXE handler 0x80066ec4, its anim descriptors are
    # the EXE table 0x80078190[sub] -> stage 8 data 0x800a0c94..0x800a7bb4; the stage objects (0x8009e1b4 / 0x8009e334
    # states) wait for +6 = 2 / 4 and also spawn type 0xd8 children (byte +0x39).  Cut: everything after the stage
    # objects' own anim scripts (end 0x800a03de) and the 5 initial CLUTs (0x800a03e0, EXE table 0x8006ee24[8]) up to
    # the spawn list (0x800a7bb8: empty, EXE table 0x8006edf0[8]) and the live state tables = the fade data and its
    # descriptors.  Patches: the timer switch returns at once; the two child spawns are skipped.  Look: the sky
    # stays daylight for the whole round.
    # Stage 4 (statue hall, the "galactic council" of the user's report): the row of monitors with alien faces that
    # flickers on in bursts at the top of the screen is BG layer 2: draw callback 0x8009fdb0 (table word 0x8009278c;
    # a0 == 0 -> layer builder 0x8009ec24(2), then 0x80011e58 on the layer's list when +0x18 is set).  `jr ra` at the
    # callback = the monitors never appear (2026-11-17 night: emulator showed no other change; the layer holds
    # nothing else).  Patch only: no bytes removed.  For the hardware A/B (Beetle measures ~0 CPU for the layer).
    4: dict(cuts=[],
            patches=[(0x8009fdb0, 0x27bdffe8, 0x03e00008),       # jr ra
                     (0x8009fdb4, 0x00042400, 0x00000000),       # nop
                     # 2026-11-18: the per-frame builder call (0x8008a404, a0 = 0xf) still rebuilt this hidden layer's
                     # tiles on every scroll (section `andi t6, 2` of 0x8009ec24): skipped (`beqz` -> `b`)
                     (0x8009f558, 0x10400118, 0x10000118)]),
    8: dict(cuts=[(0x800a0480, 0x800a7bb8)],
            patches=[(0x8009e840, 0x3c028008, 0x03e00008),       # jr ra
                     (0x8009e844, 0x8043b832, 0x00000000),       # nop
                     (0x8009e24c, 0x12000008, 0x10000008),       # beqz s0 -> b (no type 0xd8 child)
                     (0x8009e3e8, 0x12000008, 0x10000008)],
            # 2026-11-18: 0x8009ef1c `addiu v1,v0,-0x710` takes its hi from the `lui v0,0x800b` in the delay slot of the
            # bne at 0x8009eeec (the branch target path): the scanner relocated only the fall-through user 0x8009eef4,
            # so the BG layer builder 0x8009ee64 compared the camera with stale RAM and rebuilt every tile every frame
            # (+43 CPU lines per frame, Beetle).  Same hi, so the lo becomes the one of 0x8009eef4.
            # Same pattern in the other two layer builders (found by scanning every delay-slot lui's branch target).
            post=[(0x8009ef1c, 0x2443f8f0, 0x244381b8), (0x8009f338, 0x2443f8f0, 0x244381b8),
                  (0x8009f76c, 0x2443f8f0, 0x244381b8)]),
}


if os.environ.get("SL8NOCUT"):            # experiment: stage-8 patches without removing / relocating bytes
    CUTS[8] = dict(CUTS[8], cuts=[])


STAGE0_LAYER3 = dict(cuts=[(0x800ae114, 0x800af914)],
                     patches=[(0x800a0e90, 0x27bdffe8, 0x03e00008), (0x800a0e94, 0x00042400, 0x00000000),
                              (0x8009f250, 0x0c005c2e, 0x00000000)],
                     allow=[(0x8009f238, 0x8009f258), (0x8009fd54, 0x800a02c4)])


def j_(t): return 0x08000000 | ((t >> 2) & 0x03FFFFFF)


# ---------------------------------------------------------------------------------------------------- ARC parsing
def entries(b):
    n = struct.unpack_from("<I", b, 0)[0]
    return [list(struct.unpack_from("<2I", b, 4 + 8 * i)) for i in range(n)]


def code_end(b):
    """end of the stage code in RAM: after the last `jr ra` + delay slot of entry 0's initialised part"""
    o0, s0 = entries(b)[0]
    blob = b[o0:o0 + s0 - 16]
    ie = o0 + len(blob.rstrip(b"\0"))
    lj = max(i for i in range(o0, ie, 4) if b[i:i + 4] == bytes.fromhex("0800e003")) + 8
    return BASE + lj, BASE + ie


# ---------------------------------------------------------------------------------------------------- references
LOADS = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2a, 0x2b, 0x2e, 0x32, 0x3a}   # lb lh lwl lw lbu lhu lwr sb sh swl sw swr lwc2 swc2
CALLER = set(range(1, 16)) | {24, 25, 31}           # at v0 v1 a0-a3 t0-t7 t8 t9 ra: dead after a jal


def dest(w):
    """register written by instruction word w (None if none / not modelled)"""
    op = w >> 26; rs = (w >> 21) & 31; rt = (w >> 16) & 31; rd = (w >> 11) & 31; fn = w & 63
    if op == 0:
        if fn in (0x08,): return None                 # jr
        if fn == 0x09: return rd                      # jalr
        if fn in (0x18, 0x19, 0x1a, 0x1b, 0x11, 0x13, 0x0c, 0x0d): return None   # mult/div/mthi/mtlo/syscall/break
        return rd
    if op in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07): return 31 if op == 0x03 else None
    if op in (0x28, 0x29, 0x2a, 0x2b, 0x2e, 0x3a): return None    # stores
    if op == 0x10: return rt if ((w >> 21) & 31) in (0, 2) else None   # mfc0 / cfc0
    if op == 0x12: return rt if ((w >> 21) & 31) in (0, 2) else None   # mfc2 / cfc2
    if op in (0x32,): return None
    return rt


def reads(w):
    """source registers of instruction word w (integer unit; coarse)"""
    op = w >> 26; rs = (w >> 21) & 31; rt = (w >> 16) & 31; fn = w & 63
    if op == 0:
        if fn in (0x00, 0x02, 0x03): return {rt}                       # sll srl sra
        if fn in (0x10, 0x12, 0x0c, 0x0d): return set()                # mfhi mflo syscall break
        if fn in (0x08, 0x09, 0x11, 0x13): return {rs}                 # jr jalr mthi mtlo
        return {rs, rt}
    if op in (0x02, 0x03, 0x0f): return set()
    if op in (0x04, 0x05): return {rs, rt}
    if op in (0x01, 0x06, 0x07): return {rs}
    if op in (0x28, 0x29, 0x2a, 0x2b, 0x2e): return {rs, rt}           # stores
    if op in (0x10, 0x12): return {rt} if ((w >> 21) & 31) in (4, 6) else set()   # mtc / ctc
    return {rs}


def scan_code(img, lo_addr, hi_addr, tlo, thi, unknown=None):
    """lui/lo pairs in img (RAM image starting at BASE) between lo_addr..hi_addr whose target is in [tlo, thi).
    -> list of dict(lui=addr, use=addr, kind, target, crossed).  Tracks the lui value through move / addu (hi + index)
    and stack spills (sw reg, n(sp) / lw reg, n(sp)).  unknown (list): gets (lui, addr) for every other read of a
    register that holds a lui value (a use the relocation cannot follow)."""
    out = []
    H = {}                                            # reg -> (hi value, lui address, crossed)
    SP = {}                                           # stack slot -> H value
    targets = set()
    for a in range(lo_addr, hi_addr, 4):              # branch targets (join points)
        w = struct.unpack_from("<I", img, a - BASE)[0]; op = w >> 26
        if op in (0x04, 0x05, 0x06, 0x07) or (op == 0x01 and ((w >> 16) & 31) in (0, 1, 16, 17)):
            off = w & 0xffff; off = off - 0x10000 if off & 0x8000 else off
            targets.add(a + 4 + 4 * off)
    for a in range(lo_addr, hi_addr, 4):
        w = struct.unpack_from("<I", img, a - BASE)[0]
        op = w >> 26; rs = (w >> 21) & 31; rt = (w >> 16) & 31; rd = (w >> 11) & 31; fn = w & 63
        imm = w & 0xffff; simm = imm - 0x10000 if imm & 0x8000 else imm
        if a in targets:                              # join point: keep the values, flag pairs made through it
            H = {r: (v[0], v[1], True) for r, v in H.items()}
        prevw = struct.unpack_from("<I", img, a - 4 - BASE)[0] if a > lo_addr else 0
        pop = prevw >> 26
        handled = set()
        if op == 0x0f:
            H[rt] = (imm << 16, a, False)
        else:
            if op in (0x09, 0x0d) and rs in H:            # addiu / ori
                v = (H[rs][0] + (imm if op == 0x0d else simm)) & 0xffffffff
                handled.add(rs)
                if tlo <= v < thi: out.append(dict(lui=H[rs][1], use=a, kind="ori" if op == 0x0d else "addiu", target=v, crossed=H[rs][2]))
            elif op in LOADS and rs in H:
                v = (H[rs][0] + simm) & 0xffffffff
                handled.add(rs)
                if tlo <= v < thi: out.append(dict(lui=H[rs][1], use=a, kind="mem", target=v, crossed=H[rs][2]))
            if op == 0x2b and rs == 29 and rt in H:       # spill
                SP[simm] = H[rt]; handled.add(rt)
            if op == 0 and fn == 0x21 and (rs in H) != (rt in H):
                handled.add(rs if rs in H else rt)
            if op == 0 and fn == 0x25 and rt == 0 and rs in H:
                handled.add(rs)
            if unknown is not None:
                for r in reads(w):
                    if r in H and r not in handled and r != 0: unknown.append((H[r][1], a))
            # register bookkeeping
            if op == 0 and fn == 0x21 and (rs in H) != (rt in H):          # addu rd, hi, x -> rd is hi-derived
                H[rd] = H[rs] if rs in H else H[rt]
            elif op == 0 and fn == 0x25 and rt == 0 and rs in H:            # move rd, hi
                H[rd] = H[rs]
            else:
                d = dest(w)
                if d is not None and op != 0x03: H.pop(d, None)
                if op == 0x23 and rs == 29 and simm in SP: H[rt] = SP[simm]   # reload of a spilled lui value
            if op == 0x2b and rs == 29 and rt not in H: SP.pop(simm, None)
        # after the delay slot of a call: caller-saved registers are dead; of jr ra: new function; of j / jr: the
        # next word is reached from elsewhere (jump tables) -> values kept but flagged
        if pop == 0x03 or (pop == 0 and (prevw & 63) == 0x09):
            for r in CALLER: H.pop(r, None)
        if pop == 0 and (prevw & 63) == 0x08 and ((prevw >> 21) & 31) == 31:
            H = {}; SP = {}
        elif pop == 0x02 or (pop == 0 and (prevw & 63) == 0x08):
            H = {r: (v[0], v[1], True) for r, v in H.items()}
    return out


def scan_rel(img, lo_addr, hi_addr, tlo, thi):
    """base + offset uses of a register that holds a known address inside [tlo, thi): the compiler addresses one
    buffer from another's base (stage 0: `sw v0, 0x6dc4(v1)` with v1 = SPRT buffer A + index -> DR_MODE buffer A;
    stage 8: `addiu v0, s6, 0x73c0`).  -> list of dict(use, base, imm, kind).  Register values: lui+addiu/ori pairs,
    addiu chains (rd = rs + imm), addu with an unknown index (base kept), move, stack spills."""
    out = []
    H = {}; X = {}; SP = {}                          # H: reg -> hi;  X: reg -> exact base address
    for a in range(lo_addr, hi_addr, 4):
        w = struct.unpack_from("<I", img, a - BASE)[0]
        op = w >> 26; rs = (w >> 21) & 31; rt = (w >> 16) & 31; rd = (w >> 11) & 31; fn = w & 63
        imm = w & 0xffff; simm = imm - 0x10000 if imm & 0x8000 else imm
        prevw = struct.unpack_from("<I", img, a - 4 - BASE)[0] if a > lo_addr else 0
        pop = prevw >> 26
        newH = newX = None
        if op == 0x0f:
            newH = (rt, imm << 16)
        elif op in (0x09, 0x0d) and rs in H:
            v = (H[rs] + (imm if op == 0x0d else simm)) & 0xffffffff
            if tlo <= v < thi: newX = (rt, v)
        elif op == 0x09 and rs in X:
            if simm: out.append(dict(use=a, base=X[rs], imm=simm, kind="addiu"))
            newX = (rt, (X[rs] + simm) & 0xffffffff)
        elif op in LOADS and rs in X:
            if simm: out.append(dict(use=a, base=X[rs], imm=simm, kind="mem"))
        if op == 0x2b and rs == 29:
            if rt in X: SP[simm] = ("X", X[rt])
            elif rt in H: SP[simm] = ("H", H[rt])
            else: SP.pop(simm, None)
        if op == 0 and fn == 0x21 and (rs in X) != (rt in X) and rs not in H and rt not in H:
            v = X[rs] if rs in X else X[rt]; X.pop(rd, None); H.pop(rd, None); X[rd] = v
        elif op == 0 and fn == 0x21 and (rs in H) != (rt in H):
            v = H[rs] if rs in H else H[rt]; X.pop(rd, None); H.pop(rd, None); H[rd] = v
        elif op == 0 and fn == 0x25 and rt == 0 and (rs in X or rs in H):
            if rs in X: v = X[rs]; X.pop(rd, None); H.pop(rd, None); X[rd] = v
            else: v = H[rs]; X.pop(rd, None); H.pop(rd, None); H[rd] = v
        else:
            d = dest(w)
            if d is not None and op != 0x03:
                H.pop(d, None); X.pop(d, None)
            if newH: H[newH[0]] = newH[1]
            if newX: X[newX[0]] = newX[1]
            if op == 0x23 and rs == 29 and simm in SP:
                k, v = SP[simm]
                (X if k == "X" else H)[rt] = v
        if pop == 0x03 or (pop == 0 and (prevw & 63) == 0x09):
            for r in CALLER: H.pop(r, None); X.pop(r, None)
        if pop == 0 and (prevw & 63) == 0x08 and ((prevw >> 21) & 31) == 31:
            H = {}; X = {}; SP = {}
    return out


def scan_data(img, lo_addr, hi_addr, tlo, thi):
    out = []
    for a in range(lo_addr & ~3, hi_addr, 4):
        v = struct.unpack_from("<I", img, a - BASE)[0]
        if tlo <= v < thi: out.append(dict(at=a, target=v))
    return out


# ---------------------------------------------------------------------------------------------------- rebuild
def mapper(cuts):
    cuts = sorted(cuts)

    def f(x):
        d = 0
        for lo, hi in cuts:
            if x >= hi: d += hi - lo
            elif x >= lo: raise ValueError("reference into a cut: %08x in %08x-%08x" % (x, lo, hi))
        return x - d
    return f


_exe = None


def exe_word(a):
    global _exe
    if _exe is None: _exe = open(os.path.join(GAME, "disc", "SLUS_010.59"), "rb").read()
    return struct.unpack_from("<I", _exe, a - 0x80010000 + 0x800)[0]


def rebuild(b, cuts, patches=(), allow=(), verbose=False, stage=None, post=()):
    """b = stock ARC bytes.  cuts = [(lo, hi)] RAM ranges inside entry 0 (after the code).  patches = [(addr, stock,
    new)] code words.  allow = [(lo, hi)] ranges whose references INTO a cut are accepted (known-dead readers, their
    words are left as they are).  -> new ARC bytes (same length) and a report dict"""
    b = bytearray(b)
    ent = entries(b)
    o0, s0 = ent[0]
    e0lo, e0hi = BASE + o0, BASE + o0 + s0
    cend, iend = code_end(b)
    cuts = sorted(cuts)
    for lo, hi in cuts:
        assert cend <= lo < hi <= e0hi and lo % 4 == 0 and hi % 4 == 0, (hex(lo), hex(hi))
    for a, stock, new in patches:
        assert struct.unpack_from("<I", b, a - BASE)[0] == stock, "stagelite: patch site %08x not stock" % a
        struct.pack_into("<I", b, a - BASE, new)
    if not cuts:                                         # patch-only stage (no bytes removed): nothing moves
        return bytes(b), dict(bad=[], stage_cut=0, code_refs=0, data_refs=0, exe=[])
    f = mapper(cuts)
    total = sum(hi - lo for lo, hi in cuts)
    first = cuts[0][0] if cuts else e0hi
    img = bytes(b)
    inallow = lambda a: any(lo <= a < hi for lo, hi in allow)
    # code references to anything at or after the first cut, inside entry 0
    unk = []
    refs = scan_code(img, BASE + o0 + 4, cend, 0x80000000, 0x80800000, unk)   # every pair: a lui may serve several targets
    users = collections.defaultdict(list)
    for r in refs: users[r["lui"]].append(r)
    refs = [r for r in refs if first <= r["target"] < e0hi + 0x10000]
    by_lui = collections.defaultdict(list)
    bad = []
    for r in refs:
        t = r["target"]
        if t >= e0hi:
            # past entry 0: the stage code does not address entries 1+ absolutely in any stage we cut (checked in
            # show); a hit here is an index base / false pair -> report
            bad.append(("past-entry0", r)); continue
        if any(lo <= t < hi for lo, hi in cuts):
            if inallow(r["use"]): continue
            bad.append(("into-cut", r)); continue
        by_lui[r["lui"]].append(r)
    newimg = bytearray(img)
    nrel = 0
    for lui, rs in by_lui.items():
        rs = [r for r in users[lui] if not any(lo <= r["target"] < hi for lo, hi in cuts)]
        his = set()
        for r in rs:
            t2 = f(r["target"]) if BASE <= r["target"] < e0hi else r["target"]
            his.add((t2 >> 16) if r["kind"] == "ori" else ((t2 + 0x8000) >> 16) & 0xffff)
        if len(his) != 1:
            bad.append(("hi-conflict", rs)); continue
        hi = his.pop()
        w = struct.unpack_from("<I", newimg, lui - BASE)[0]
        if hi != w & 0xffff:
            for l, at in unk:
                if l == lui: bad.append(("lui-%08x-other-use" % lui, "%08x" % at))
        struct.pack_into("<I", newimg, lui - BASE, (w & 0xffff0000) | hi)
        for r in rs:
            t2 = f(r["target"]) if BASE <= r["target"] < e0hi else r["target"]
            w = struct.unpack_from("<I", newimg, r["use"] - BASE)[0]
            struct.pack_into("<I", newimg, r["use"] - BASE, (w & 0xffff0000) | (t2 & 0xffff)); nrel += 1
    # base + offset spans across a cut: the offset must shrink by the cut bytes between base and target
    nspan = 0
    for r in scan_rel(img, BASE + o0 + 4, cend, BASE + o0, e0hi):
        t0, t1 = r["base"], r["base"] + r["imm"]
        if not (BASE <= t1 < e0hi): continue
        if any(lo <= t1 < hi for lo, hi in cuts) or any(lo <= t0 < hi for lo, hi in cuts):
            if inallow(r["use"]): continue
            bad.append(("span-into-cut", "%08x %08x+%x" % (r["use"], t0, r["imm"]))); continue
        n = f(t1) - f(t0)
        if n != r["imm"]:
            if inallow(r["use"]): continue
            w = struct.unpack_from("<I", newimg, r["use"] - BASE)[0]
            assert -0x8000 <= n < 0x8000
            struct.pack_into("<I", newimg, r["use"] - BASE, (w & 0xffff0000) | (n & 0xffff)); nspan += 1
    # pointer words in the init data (outside the cuts) pointing at or past the first cut, inside entry 0
    drefs =[r for r in scan_data(img, cend, iend, first, e0hi) if not any(lo <= r["at"] < hi for lo, hi in cuts)]
    ndat = 0
    for r in drefs:
        if any(lo <= r["target"] < hi for lo, hi in cuts):
            if inallow(r["at"]): continue
            bad.append(("data-into-cut", r)); continue
        struct.pack_into("<I", newimg, r["at"] - BASE, f(r["target"])); ndat += 1
    # compact entry 0, shift entries 1-5 down
    out = bytearray()
    pos = 0
    for lo, hi in cuts:
        out += newimg[pos:lo - BASE]; pos = hi - BASE
    out += newimg[pos:]
    hdr = entries(out)
    hdr[0][1] = s0 - total
    for k in range(1, len(hdr)): hdr[k][0] -= total
    for k, (o, s) in enumerate(hdr): struct.pack_into("<2I", out, 4 + 8 * k, o, s)
    out += bytes(len(b) - len(out))
    rep = dict(stage_cut=total, code_refs=nrel, data_refs=ndat, spans=nspan, bad=bad, cend=cend, iend=iend, exe=[])
    if stage is not None:                             # EXE pointers that belong to this stage
        for tab, n in ((EXE_SPAWN, 16), (EXE_PAL, 5 * 32)):
            p = exe_word(tab + 4 * stage)
            if any(p < hi and p + n > lo for lo, hi in cuts): bad.append(("exe-table-%08x-in-cut" % tab, hex(p)))
            elif first <= p < e0hi: rep["exe"].append((tab + 4 * stage, p, f(p)))
    if verbose:
        print("cut %d B, %d code refs (%d lui), %d base+offset spans, %d data words relocated, %d problems" % (total, nrel, len(by_lui), nspan, ndat, len(bad)))
        for k, r in bad: print("  ", k, r if isinstance(r, (dict, str)) else ["%08x" % x["use"] for x in r])
        for a, o, n in rep["exe"]: print("   EXE %08x: %08x -> %08x" % (a, o, n))
    for a, before, after in post:                     # fixes applied after the relocation (stock word relocated)
        assert struct.unpack_from("<I", out, a - BASE)[0] == before, "stagelite post patch %08x: %08x" % (a, struct.unpack_from("<I", out, a - BASE)[0])
        struct.pack_into("<I", out, a - BASE, after)
    return bytes(out), rep


# ---------------------------------------------------------------------------------------------------- disc access
def read_stage(st, read=None):
    if read is None:
        from iso import Disc
        d = Disc(os.path.join(GAME, "disc", "mvc.bin"))
        for f, lba, sz, fl in d.walk():
            if f == "DAT/BG%02d.ARC" % st: return d.read(lba, sz)
    return read("BG%02d.ARC" % st)


def selected(argv):
    a = next((x for x in argv if x.startswith("--stagelite")), None)
    if a is None: return []
    if "=" in a: return [int(x) for x in a.split("=", 1)[1].split(",") if x]
    return sorted(CUTS)


def files(read, stages):
    """-> ([(file name, new bytes)], [(EXE address, 4 bytes)]) for mktag.py (read(name) -> stock bytes)"""
    out = []; exe = []
    for st in stages:
        c = CUTS[st]
        data, rep = rebuild(read("BG%02d.ARC" % st), c["cuts"], c.get("patches", ()), c.get("allow", ()), stage=st, post=c.get("post", ()))
        assert not rep["bad"], ("stagelite stage %d: unresolved references" % st, rep["bad"][:4])
        out.append(("BG%02d.ARC" % st, data))
        for a, o, n in rep["exe"]:
            assert exe_word(a) == o
            exe.append((a, struct.pack("<I", n)))
        print("stagelite: stage %d -%d B (%d code refs, %d data words, %d EXE words relocated)" % (st, rep["stage_cut"], rep["code_refs"], rep["data_refs"], len(rep["exe"])))
    return out, exe


def saved(st):
    return sum(hi - lo for lo, hi in CUTS[st]["cuts"]) if st in CUTS else 0


def disc(name, stages):
    """stock disc + stagelite ARCs -> games/mvc/build/NAME.bin/.cue (A/B tests on the stock game)"""
    import shutil, json
    sys.path.insert(0, os.path.join(GAME, "tools", "tagload"))
    from mktag import Img, lba_map
    from iso import Disc
    LBA = lba_map()
    src = Disc(os.path.join(GAME, "disc", "mvc.bin"))
    out = os.path.join(GAME, "build", name + ".bin")
    shutil.copyfile(os.path.join(GAME, "disc", "mvc.bin"), out)
    img = Img(out)
    fl, exe = files(lambda fn: src.read(*LBA[fn]), stages)
    for fn, data in fl:
        img.wbytes(LBA[fn][0], 0, data)
    for a, d in exe:
        img.wbytes(LBA["SLUS_010.59"][0], a - 0x80010000 + 0x800, d)
    img.fix()
    json.dump(dict(patches=[(a, d.hex()) for a, d in exe]), open(os.path.join(GAME, "build", name + ".patches.json"), "w"))
    open(os.path.join(GAME, "build", name + ".cue"), "w").write(f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print("->", out)


if __name__ == "__main__":
    a = sys.argv
    if a[1] == "show":
        st = int(a[2]); c = CUTS[st]
        rebuild(read_stage(st), c["cuts"], c.get("patches", ()), c.get("allow", ()), verbose=True, stage=st)
    elif a[1] == "disc":
        disc(a[2], [int(x) for x in a[3:]] or sorted(CUTS))
