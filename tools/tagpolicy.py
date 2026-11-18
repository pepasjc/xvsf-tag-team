"""Python model of the battle loader's per-battle policy (tools/tagload/tagload.c:
effplan / choose / guard / upgrade / plan).

    python tagpolicy.py                     distribution over all 2380 four-character teams
                                            x 6 main/partner splits x 11 stages (= 157,080 cases),
                                            next to the tag12 and tag13 policies on the same files
    python tagpolicy.py P1m,P1p,P2m,P2p@stage ...     what the loader will do for these teams

Sprite tiers per character, smallest to largest:
    strong (1, build/STRONGDIR, XVH1) < base (0, build/FASTDIR, in place) < mid (3, build/MIDDIR) < fat (2, build/FATDIR)
    a character whose mid file is identical to its base file costs 0 to make mid ("already mid")

plan(list, stage) -> dict(eff, tier, mid, fat, strong, dropped, list, heaptop, start, end)
    eff      1 = stock RLE effects file, 0 = XVM1 effects file
    tier     per slot (P1 main, P1 partner, P2 main, P2 partner): 0 base, 1 strong, 2 fat, 3 mid
    mid/fat/strong   slot masks (bit n = slot n) of the slots loaded with exactly that tier
    dropped  0, 3 (P2 partner dropped) or 1|3
Debug block on the console (0x80017350): byte0 dropped, byte1 = loaded mask | mid << 4, byte2 strong,
byte3 = fat | eff << 7, u32 data start, u32 data end.
"""
import os, itertools, collections, sys, struct, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
POOL, LIMIT, HEAPBASE = 19296, 0x801fe000, 0x80098000
FASTDIR, STRONGDIR, MIDDIR, FATDIR = "nspm", "nsp" if "--nospeed" in sys.argv else "nsph4", "nspm4", "nspfat2"
# 1.1: strong tier = XVH1 + its most decoded tiles as stock RLE (work/speed/decode/strongrle.py 4); --nospeed: 1.0.x files
EFF_DEFAULT = os.path.join(ROOT, "build", "nspm_eff", "SP_EFF1.NSP")
EFF_STOCK = os.path.join(ROOT, "disc", "files", "A", "A2", "SP_EFF1.NSP")
# heap offset before SP_EFF1 is loaded, per stage (work/heaptops2.py, stock disc; the stage and the
# other effect files are the same on every build)
S2PRE = {0: 124576, 1: 67144, 2: 78412, 3: 90404, 4: 72000, 5: 86704, 6: 120716, 7: 122288, 8: 115044, 9: 104504, 10: 80372}
ORDER = (3, 1, 2, 0)                    # strong: P2 partner, P1 partner, P2 main, P1 main; upgrades: the reverse
T_BASE, T_STRONG, T_FAT, T_MID = 0, 1, 2, 3
TIERDIR = {T_BASE: FASTDIR, T_STRONG: STRONGDIR, T_FAT: FATDIR, T_MID: MIDDIR}
TIERNAME = {T_BASE: "base", T_STRONG: "strong", T_FAT: "fat", T_MID: "mid"}


def _sz(d, c):
    return os.path.getsize(os.path.join(ROOT, "build", d, f"SP_PL{c:02X}.NSP"))


import region
CODE = {c: os.path.getsize(os.path.join(region.FILES, "P", "P0", f"PL{11 if c == 18 else c:02X}_10.BIN")) for c in range(19)}
SPR = {t: {c: _sz(d, c) for c in range(19)} for t, d in TIERDIR.items()}
EFFSIZE = (os.path.getsize(EFF_DEFAULT), os.path.getsize(EFF_STOCK))


def tier_file(c, t):
    """path of the file the loader reads for character c at tier t"""
    return os.path.join(ROOT, "build", TIERDIR[t], f"SP_PL{c:02X}.NSP")


def heaptop(stage, stock):
    return HEAPBASE + ((((S2PRE[stage] + ((EFFSIZE[stock] + 3) & ~3)) >> 3) + 1) << 3)


HEAPTOP = {st: heaptop(st, 1) for st in S2PRE}          # stock effects (= the original game)


def need(c, v=0, spr=None):
    return ((((CODE[c] >> 3) + 1) << 3) + (spr or SPR)[v][c] + 7) & ~7


def choose(lst, cap, spr=None):
    """-> strong mask, or None when even all-strong does not fit."""
    t = sum(need(c, 0, spr) for c in lst if c >= 0)
    if t <= cap: return 0
    for i in ORDER:
        if lst[i] >= 0 and t - need(lst[i], 0, spr) + need(lst[i], 1, spr) <= cap: return 1 << i
    m = 0
    for i in ORDER:
        if lst[i] >= 0:
            t -= need(lst[i], 0, spr) - need(lst[i], 1, spr); m |= 1 << i
            if t <= cap: return m
    return None


def guard(lst, top, spr=None):
    """-> (strong mask, dropped mask, list)"""
    lst = list(lst); cap = LIMIT - top - POOL; dropped = 0
    for i in (3, 1, -1):
        m = choose(lst, cap, spr)
        if m is not None: return m, dropped, lst
        assert i > 0
        if lst[i] >= 0: lst[i] = -1; dropped |= i
    raise AssertionError


def total(lst, tier):
    return sum(need(c, tier[i]) for i, c in enumerate(lst) if c >= 0)


def upgrade(lst, tier, slack, to):
    for i in reversed(ORDER):                           # P1 main, P2 main, P1 partner, P2 partner
        if lst[i] >= 0:
            d = need(lst[i], to) - need(lst[i], tier[i])
            assert d >= 0
            if d <= slack: slack -= d; tier[i] = to
    return slack


def dedupe(team):
    """the game's own dedupe (0x8002af74): mains first, then partners; -1 = shares data"""
    lst = list(team); seen = {lst[0]}
    if lst[2] in seen: lst[2] = -1
    else: seen.add(lst[2])
    for i in (1, 3):
        if lst[i] in seen: lst[i] = -1
        else: seen.add(lst[i])
    return lst


def plan(team, stage):
    lst = dedupe(team)
    # effplan (before the effects file is loaded)
    topx, tops = heaptop(stage, 0), heaptop(stage, 1)
    cap = LIMIT - POOL - topx
    eff = 0
    if choose(lst, cap) == 0:
        t = [0, 0, 0, 0]
        if upgrade(lst, t, cap - total(lst, t), T_MID) >= tops - topx: eff = 1
    # plan (real heap top)
    top = heaptop(stage, eff); cap = LIMIT - POOL - top
    strong, dropped, lst = guard(lst, top)
    tier = [(strong >> i) & 1 for i in range(4)]
    if strong == 0:
        upgrade(lst, tier, upgrade(lst, tier, cap - total(lst, tier), T_MID), T_FAT)
    end = top + POOL + total(lst, tier)
    assert end <= LIMIT
    mask = lambda t: sum(1 << i for i in range(4) if lst[i] >= 0 and tier[i] == t)
    return dict(eff=eff, tier=tier, mid=mask(T_MID), fat=mask(T_FAT), strong=strong, dropped=dropped, list=lst,
                heaptop=top, start=top + POOL, end=end)


BOSSLIMIT = 0x801e5000                  # boss fights on the new loader must end below the ending renderer's buffers
RLE8 = os.path.getsize(os.path.join(ROOT, "disc", "files", "A", "A0", "SP_PL08.NSP"))


def plan_boss(team, stage, p1boss=True):
    """Boss fight on the new loader (tagload.c bossprep/bplan): None when the stock path is used.
    Players FAT, Apocalypse = stock RLE file, stock effects, fixed pool.  debug byte 0 = 0xF9."""
    lst = dedupe(team)
    p2 = team[2] == 8 and team[0] != 8 and team[1] != 8 and lst[0] >= 0 and lst[2] == 8 and lst[3] < 0
    p1 = p1boss and team[0] == 8 and team[2] != 8 and team[3] != 8 and lst[2] >= 0 and lst[0] == 8 and lst[1] < 0   # 1.3 (-DBOSSP1)
    if not (p1 or p2): return None
    top = heaptop(stage, 1)
    boss = ((((CODE[8] >> 3) + 1) << 3) + RLE8 + 7) & ~7
    sizes = {i: (boss if c == 8 else need(c, T_FAT)) for i, c in enumerate(lst) if c >= 0}
    end = top + POOL + sum(sizes.values())
    if end > BOSSLIMIT: return None
    return dict(eff=1, list=lst, tier=[T_MID if c == 8 else T_FAT for c in lst], fat=sum(1 << i for i, c in enumerate(lst) if c >= 0 and c != 8),
                mid=sum(1 << i for i, c in enumerate(lst) if c == 8), strong=0, dropped=0xF9, heaptop=top, start=top + POOL, end=end, sizes=sizes)


def plan_old(team, stage, base, fat=T_FAT):
    """the tag12/tag13 policy (default tier `base` in place, stock effects first, then fat) on the
    current files: tag12 = base T_BASE, tag13 = base T_MID"""
    spr = {0: SPR[base], 1: SPR[T_STRONG], 2: SPR[fat]}
    lst = dedupe(team)
    eff = 1 if choose(lst, LIMIT - POOL - heaptop(stage, 1), spr) == 0 else 0
    top = heaptop(stage, eff)
    strong, dropped, lst = guard(lst, top, spr)
    tier = [T_STRONG if strong >> i & 1 else base for i in range(4)]
    if strong == 0:
        cap = LIMIT - POOL - top - sum(need(c, 0, spr) for c in lst if c >= 0)
        for i in reversed(ORDER):
            if lst[i] >= 0:
                d = need(lst[i], 2, spr) - need(lst[i], 0, spr)
                if d <= cap: cap -= d; tier[i] = T_FAT
    return dict(eff=eff, tier=tier, strong=strong, dropped=dropped, list=lst)


# ---- 1.1 continuous hot-tile tier (tools/speed/decode/hotfile.py, tagload.c hplan): non-strong characters load the
# base file minus the last S bytes + the first R bytes of their hot region; steps per character in HOTDIR/steps.json
# as (items, S, R, gain); gain = play volume x (XVM1 - RLE cycles) of the items.
HOTDIR = os.path.join(ROOT, "build", "nsphot")
try:
    HOTSTEPS = {int(k, 16): v for k, v in json.load(open(os.path.join(HOTDIR, "steps.json"))).items()}
except OSError:
    HOTSTEPS = {}


def hnet(c, s):
    """extra RAM of step s (0 = base file only) over the base file, as tagload.c hcost() counts it"""
    if s == 0: return 0
    k, S, R, G = HOTSTEPS[c][s - 1]
    f = SPR[T_BASE][c]
    return ((f - S + 3) & ~3) + R - ((f + 3) & ~3) + 8


def hgain(c, s):
    """gain of step s (1-based) as stored in the hot directory sector (u16, x3000)"""
    G = HOTSTEPS[c][s - 1][3]; G0 = HOTSTEPS[c][s - 2][3] if s > 1 else 0.0
    return int(round((G - G0) * 3000))


def hplan(lst, tier, slack):
    """tagload.c hplan(): greedy over the four characters' next steps by gain per byte (first best wins ties);
    a character whose next step does not fit stops there (the region is read as a prefix).  -> step per slot"""
    step = [0, 0, 0, 0]
    live = [lst[i] >= 0 and tier[i] == T_BASE and bool(HOTSTEPS.get(lst[i])) for i in range(4)]
    while True:
        b = -1; bg = 0; bd = 1
        for i in range(4):
            if not live[i]: continue
            c = lst[i]; k = step[i]
            d = hnet(c, k + 1) - hnet(c, k); g = hgain(c, k + 1)
            if b < 0 or g * bd > bg * d: b, bg, bd = i, g, d
        if b < 0: break
        if bd <= slack:
            slack -= bd; step[b] += 1
            if step[b] == min(9, len(HOTSTEPS[lst[b]])): live[b] = False
        else: live[b] = False
    return step


def plan_hot(team, stage):
    """1.1 policy: effects decision and strong/drop guard as plan(); no mid/fat; hot steps from the slack"""
    p = plan(team, stage)
    lst = p["list"]; top = p["heaptop"]
    tier = [T_STRONG if p["strong"] >> i & 1 else T_BASE for i in range(4)]
    slack = LIMIT - POOL - top - total(lst, tier)
    step = hplan(lst, tier, slack)
    end = top + POOL + total(lst, tier) + sum(hnet(lst[i], step[i]) for i in range(4) if lst[i] >= 0)
    assert end <= LIMIT
    return dict(p, tier=tier, step=step, end=end, mid=0, fat=0)


def atleast_mid(c, t):
    return t in (T_MID, T_FAT) or (t == T_BASE and SPR[T_MID][c] == SPR[T_BASE][c])


def stats(fn):
    chars = [c for c in range(18) if c != 8]
    out = {}
    tot = collections.Counter()
    for st in list(S2PRE) + ["all"]:
        if st == "all": out[st] = tot; break
        h = collections.Counter()
        for t in itertools.combinations(chars, 4):
            for a, b in itertools.combinations(range(4), 2):         # which two are the mains
                rest = [x for x in range(4) if x not in (a, b)]
                p = fn([t[a], t[rest[0]], t[b], t[rest[1]]], st)
                h["n"] += 1; h["eff"] += p["eff"]; h["s0"] += p["strong"] == 0; h["drop"] += p["dropped"] != 0
                h["f%d" % sum(1 for i in range(4) if p["list"][i] >= 0 and p["tier"][i] == T_FAT)] += 1
                for i in range(4):
                    role = "main" if i in (0, 2) else "part"
                    h[role + "_n"] += 1
                    if p["list"][i] >= 0 and atleast_mid(p["list"][i], p["tier"][i]): h[role + "_mid"] += 1
        out[st] = h; tot.update(h)
    return out


def show(name, res):
    print(f"\n{name}")
    print("stage  zero-strong  dropped  stock-eff   mains>=mid  partners>=mid    fat: 0     1     2     3     4")
    for st, h in res.items():
        n = h["n"]
        print(f"{str(st):>5}  {100 * h['s0'] / n:10.1f}%  {h['drop']:7d}  {100 * h['eff'] / n:8.1f}%   {100 * h['main_mid'] / h['main_n']:9.1f}%  "
              f"{100 * h['part_mid'] / h['part_n']:12.1f}%        " + " ".join(f"{100 * h['f%d' % k] / n:5.1f}" for k in range(5)))


def main():
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            ids, _, st = a.partition("@")
            p = plan([int(x) for x in ids.split(",")], int(st))
            print(a, f"eff={'stock' if p['eff'] else 'XVM1'} tiers={[TIERNAME[t] if c >= 0 else '-' for t, c in zip(p['tier'], p['list'])]} "
                     f"mid={p['mid']:04b} fat={p['fat']:04b} strong={p['strong']:04b} dropped={p['dropped']} "
                     f"start={p['start']:08x} end={p['end']:08x} free={LIMIT - p['end']}")
        return
    print("effects file: XVM1", EFFSIZE[0], "stock", EFFSIZE[1])
    print("mid == base (already mid, cost 0):", [c for c in range(19) if SPR[T_MID][c] == SPR[T_BASE][c]])
    show("tag14 policy (base nspm in place; slack -> mid mains, mid partners, stock effects, fat)", stats(plan))
    show("tag12 policy on the same files (base nspm in place; slack -> stock effects, fat)", stats(lambda t, s: plan_old(t, s, T_BASE)))
    show("tag13 policy (default = nspm4 in place; slack -> stock effects, fat)", stats(lambda t, s: plan_old(t, s, T_MID)))


if __name__ == "__main__":
    main()
