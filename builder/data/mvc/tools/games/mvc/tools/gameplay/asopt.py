"""EX OPTIONS "ASSIST" ON / OFF + "ASSIST MODE" NORMAL / ROULETTE (assist-bugs helper C, 2026-11-21; mktag.py --asopt,
needs --exopt --assist --assistsel).  Rows: exopt.rows(); value bytes optrows.BYTES (fixed, session RAM, 0 = default):
    ASSIST       0x8001175f   0 ON (default), 1 OFF
    ASSIST MODE  0x80011760   0 NORMAL (default), 1 ROULETTE
Both in the EX OPTIONS block 0x8001175c-0x8001176c (zeroed by mktag, never written by stock code).

What the select's special-partner object (kind 6, SEL01 code 0x8019881c.., state table 0x801b8ed8) does, measured on
rc4.7 (work/asbug/c/selprobe.py): with the versus flag 0x8007b75d set (VERSUS / ARCADE / TRAINING: always in the tag
select) it is the stock GRID PICKER: "SPECIAL PARTNER" panel of 20 icons + the 2 secret ones (0x14 / 0x15), d-pad
moves the highlight (0x801994b0: UP / DOWN -4, LEFT / RIGHT -1 / +1, the id 0x8007b8d8 / da follows at once), a
button confirms, else the 0x100-frame timer (state 4) confirms the highlighted one.  The flag-0 path (CROSS OVER,
removed from our menu) is the stock ROULETTE: random start (state 0), the index steps every 2 frames over the 20
icons (0x80199460 + 0x80198ac4), a button stops it (0x8019937c), else it stops by itself after 41-79 frames.
So rc4.6 / rc4.7 already give the picker; NORMAL keeps exactly that (no word changes), ROULETTE switches the object to
its flag-0 roulette path.

Patches (DAT/SEL01.ARC only; code in the unused tail of assistsel's dead state-6 span, after its asbit / vsas):
  OFF, select:  0x801902cc `nop` (after state 10's `jal asbit`, delay `lb v1,1(s2)`) -> `jal clr`; delay slot = the
                stock `srav v0,v0,v1`.  clr: ASSIST == OFF -> ASSIST_BITS 0x8007b744 = 0 and v0 = 0 -> state 10 takes
                the stock "no special partner" path (no picker / roulette object); ON -> v0 untouched.
  OFF, VS:      0x801970b0 `lui v1,0x801c` (portrait init, after selscreen's / assistsel's `jal vsas` at 0x801970a4)
                -> `jal asvs` (delay = stock `lb a0,0x2d(s2)`): asvs = `lui v1,0x801c` + clr.  Clears the bits that
                vsas sets for the ARCADE CPU side (and anything else) before the battle load -> tag loader as_on 0,
                AS_SAVE 0 -> battle-init stub ASSIST_BITS = 0.
  ROULETTE:     the object's versus-flag reads that pick picker vs roulette -> `jal aspick` (v0 = ASSIST MODE == 0,
                i.e. 1 = picker, 0 = roulette; clobbers t0 / ra only; the sites are followed by a `nop`):
                0x80198878 (state 0: start index), 0x80198a24 (state 4: 0x100 timer vs random stop),
                0x80198a84 (spin: picker input vs roulette step), 0x80198b2c (`lb v0,0x75(s0)`: button stops the
                roulette).  0x80198aec (secret-code input) and 0x80198b60 (confirm sound) keep the real flag.
ARCADE CPU random assist (selscreen CPUTEAM + assistsel vsas) untouched in both modes; with OFF it is cleared by asvs.

`--asrou` (rc4.9, user decision: ROULETTE = default, arcade rules; needs --asopt): the MODE byte's meaning flips, so the
cold-boot value 0 = ROULETTE (row reads ROULETTE / NORMAL, exopt.rows): aspick = `sltu v0,zero,v0` (1 picker when the
byte is 1).  And the stock code reader 0x80198aec (`lb v0,versus flag`) -> `jal aspick` too, so ROULETTE runs the WHOLE
stock flag-0 roulette = the arcade rules (work/asrou probes, SEL01 0x80198a84.. / 0x801993c8 / 0x80199460 / 0x8019937c):
  * index steps every 2 frames over the 20 regular partners (icon order, table 0x801b8d48 = ids * 4) from a random start;
  * any punch / kick PRESS (edge, 0x770 of 0x80085040) stops it on the highlighted partner that frame (timer 1) ->
    timing pick; no press -> stops by itself after a random 41..79 frames;
  * code: START (pad function 0x1000 -> per-side bit 0x80084e55) + a punch / kick combination HELD (from the 2nd
    character's pick) is read when the index wraps to 0 (start of a lap): value LP 1 + MP 2 + HP 4 + LK 8 + MK 16 +
    HK 32; 1..20 -> the roulette stops on partner N of the order (timer 2N-1), 21 (LP+MK+HP) -> secret 0x14 (Shadow),
    22 (MP+MK+HP) -> secret 0x15 (Sentinel) at once.  A button held WITHOUT START closes the code window (0x7d) for this
    roulette.  = the arcade's "hold START + buttons when choosing the 2nd character" partner codes.
NORMAL (byte 1) = rc4.8 NORMAL (picker; the code-reader site reads 1 -> skipped as with the versus flag).
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import selscreen, assistsel
from selscreen import Asm, FILE, BASE, JAL, lo

ASSIST, AMODE = 0x8001175f, 0x80011760          # optrows.BYTES["ASSIST"], ["ASSIST MODE"]
BITS = 0x8007b744
LIMIT = assistsel.LIMIT                         # 0x80190170: end of the dead state-6 path
SITE_SEL, SITE_VS = 0x801902cc, 0x801970b0
PICK_SITES = (0x80198878, 0x80198a24, 0x80198a84, 0x80198b2c)
STOCK = {SITE_SEL: 0x00000000, SITE_VS: 0x3C03801C,
         0x80198878: 0x8042B75D, 0x80198a24: 0x8042B75D, 0x80198a84: 0x8042B75D, 0x80198b2c: 0x82020075}
NEXT_NOP = (0x80198878, 0x80198a24, 0x80198a84, 0x80198b2c)   # their next word is a nop (delay slot of our jal)
ROU_SITE = 0x80198aec                           # --asrou: stock code reader gate (`lb v0,-0x48a3(v0)`, next word nop)
STOCK_ROU = {ROU_SITE: 0x8042B75D}


def rou(argv=None):
    return "--asrou" in (sys.argv if argv is None else argv)


def org():
    code, L = assistsel.build()
    return (assistsel.ORG + len(code) + 3) & ~3


def build(r=None):
    r = rou() if r is None else r
    ORG = org()
    a = Asm(ORG)
    a.label("asvs")
    a.lui("$v1", 0x801c)                         # the replaced word at 0x801970b0, then clr
    a.label("clr")                               # ASSIST OFF: no assist bits, v0 = 0; ON: nothing (t0 / t1 only)
    a.lui("$t0", ASSIST >> 16)
    a.lbu("$t0", ASSIST & 0xFFFF, "$t0")
    a.lui("$t1", 0x8008)
    a.beq("$t0", "$zero", "clr_ret")
    a.nop()
    a.sb("$zero", lo(BITS), "$t1")
    a.ori("$v0", "$zero", 0)
    a.label("clr_ret")
    a.jr("$ra")
    a.label("aspick")                            # (clr's delay slot = aspick's first word: harmless there)
    a.lui("$t0", AMODE >> 16)                    # v0 = 1 picker (NORMAL), 0 roulette (ROULETTE)
    a.lbu("$v0", AMODE & 0xFFFF, "$t0")
    a.jr("$ra")
    if r: a.sltu("$v0", "$zero", "$v0")          # --asrou: byte 0 = ROULETTE (default), 1 = NORMAL
    else: a.sltiu("$v0", "$v0", 1)               # 2nd instruction after the load: no load-delay hazard
    code = a.assemble(); L = a.labels()
    assert ORG + len(code) <= LIMIT, f"asopt code too big: {len(code)} B at {ORG:08x}, room {LIMIT - ORG}"
    return bytes(code), L


def ram_patches(r=None):
    r = rou() if r is None else r
    code, L = build(r)
    p = [(org(), code), (SITE_SEL, struct.pack("<I", JAL(L["clr"]))), (SITE_VS, struct.pack("<I", JAL(L["asvs"])))]
    p += [(s, struct.pack("<I", JAL(L["aspick"]))) for s in PICK_SITES + ((ROU_SITE,) if r else ())]
    return p


def overlay_patches(r=None):
    """[(file, offset, bytes)] for DAT/SEL01.ARC (after selscreen's + assistsel's)"""
    return [(FILE, a - BASE, d) for a, d in ram_patches(r)]


def check_file(data, r=None):
    """data = SEL01 as the build has it BEFORE our patches (selscreen + assistsel applied)"""
    r = rou() if r is None else r
    for a, o in list(STOCK.items()) + (list(STOCK_ROU.items()) if r else []):
        assert struct.unpack_from("<I", data, a - BASE)[0] == o, f"asopt: {FILE} {a:08x} not stock"
    for a in NEXT_NOP + ((ROU_SITE,) if r else ()):
        assert struct.unpack_from("<I", data, a + 4 - BASE)[0] == 0, f"asopt: {a + 4:08x} not a nop"
    ORG = org()
    for a in range(ORG, ORG + len(build()[0]), 4):          # dead state-6 path, still stock there
        assert assistsel.ORG <= a < LIMIT


if __name__ == "__main__":
    code, L = build()
    print("asrou" if rou() else "rc4.8 mode bytes")
    print(len(code), "B at %08x (room %d);" % (org(), LIMIT - org()), {k: hex(v) for k, v in L.items()})
    for a, d in ram_patches():
        print("%08x %s" % (a, d.hex() if len(d) == 4 else "%d B" % len(d)))
