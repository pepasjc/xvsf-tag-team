"""MvC built-in achievement set: RetroAchievements game 11314 ("Marvel vs. Capcom: Clash of Super Heroes", 75 core
achievements, 575 points), adapted to the tag hack.  The conditions read the derived bytes of port.c (struct vars at
V = ACH_BASE + 0x20), which compute the set's own gates from the same game bytes, so that every achievement but one is
"pure" (cheap, skipped while its bytes do not change).  MAP: class and note per achievement (docs/ACHIEVEMENTS.md).
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
V = 0x00c020
SIDE, MAIN, ACT, COMBO, FULL, CLEAR, CLEAR8, GATE, FIN, GROUP, MGROUP, SGATE, CGATE, RYU, NODOWN = (V + i for i in range(15))
H = lambda a: "0xH%06x" % a
D = lambda a: "d0xH%06x" % a


def load():
    p = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "work", "ach", "ra_11314_patch.json"), encoding="utf-8"))
    return [a for a in p["Achievements"] if a["ID"] < 101000000]


def char_of(m):
    x = re.search(r"0xH07b8aa=(\d+)", m)
    return int(x.group(1)) if x else None


def adapt(a):
    i, m = a["ID"], a["MemAddr"]
    if 112445 <= i <= 112466:
        return f"{H(CLEAR)}=1_{H(MAIN)}={char_of(m)}", "adapt", "3-rounds option dropped (tag rules: one round); clear gate in port.c; main fighter = first pick (kept)"
    if i in (112516, 112517):
        return f"{H(CLEAR8)}=1_{H(MGROUP)}={2 if i == 112516 else 1}", "adapt", "3-rounds option dropped; group of the first pick (Onslaught in neither)"
    if 112467 <= i <= 112488:
        return f"{H(GATE)}=1_{H(ACT)}={char_of(m)}_{H(FIN)}=6", "remap", "character = the one on point (the partner can land the hyper); finish code of the round end"
    if i in (112492, 112493):
        return f"{H(GATE)}=1_{H(GROUP)}={1 if i == 112492 else 2}_{H(FIN)}=8", "remap", "group of the on-point character"
    if i == 112489:
        return f"{H(GATE)}=1_{H(FIN)}=1", "keep", "finish code 1 (the gate also asks 0x07bdc8 != 0, as the set's other finishes)"
    if i == 112490:
        return f"{H(GATE)}=1_{H(FIN)}=7_0xH07bdc8=1", "keep", "finish code 7"
    if i == 112491:
        return "0xH07b740=0_0xH07cafb=0_0xH07b82a=2_0xH07c534=0_0xH07b84c=2", "keep", "ResetIf written as its negation (pure); mode from 0x07b740 (the menu cursor 0x07b6f4 moved with the new items)"
    if i in (112494, 112495):
        return f"{H(RYU)}={2 if i == 112494 else 4}_{H(ACT)}=18", "remap", "Ryu on point (first or second pick)"
    if 112496 <= i <= 112498:
        st = re.search(r"0xH07bdf2>(\d+)", m).group(1); sc = re.search(r"0xX07c168>=(\d+)", m).group(1)
        return f"{H(SGATE)}=1_0xH07bdf2>{st}_0xX07c168>={sc}", "keep", "same bytes (gate in port.c)"
    if i in (112499, 112500):
        return f"{H(GATE)}=1_{H(FULL)}=1_{H(GROUP)}={1 if i == 112499 else 2}", "remap", "both team members at full life; group of the on-point character"
    if 112501 <= i <= 112515:
        n = int(re.search(r"0xH07c828>=(\d+)", m).group(1)); c = int(re.search(r"0xH07b8aa!=(\d+)", m).group(1))
        return f"{H(CGATE)}=1_{H(ACT)}={c}_{H(COMBO)}>={n}_{D(COMBO)}={n - 1}", "remap", "on-point character, hit count of its object (+0x138)"
    if i == 112518:
        return (m.replace("_0xH07b71e=1", "").replace("0xH07b6f4", "0xH07b740"), "adapt",
                "3-rounds option dropped; mode from 0x07b740; the set's own continue logic (hit counts) kept")
    if i == 112519:
        return f"{H(CLEAR)}=1_{H(NODOWN)}=1", "adapt", "one round per fight: 'no lost round' -> no character of yours knocked out in the run"
    raise ValueError(i)


# (ach audit 2026-11-21, `mktag.py --achfix` / env MVC_ACHFIX=1): the RA set's hyper finishes accept ANY hyper of the
# character (its descriptions say "one of X's Hyper Combos"), but most titles name one hyper (user report: War
# Destroyer unlocked "Proton Cannon").  With the fix the core latches MVL (derived byte 15) = 0x80 | the on-point
# character's move number (object +0x98) on the first frame of P1's round win: titles that are a hyper of that character
# need that move (numbers traced in Beetle, work/achaudit: tr6 / tr7 sheets + aud.py KO tests), whatever the finish code
# (the game gives Proton Cannon 4, War Destroyer 6); the others keep the set's rule (finish code 6).  The gate also needs
# P1's round win (core), so "Perfect" no longer unlocks when only the opponent's first character falls.
# Numbers = the value at the KO (multi-part hypers move on: Venom Web 0x37 -> 0x3b, Hyper Roll 0x46 -> 0x4c once they hit).
MVL = V + 15
# Round 2 (2026-11-22, also --achfix): core derive works for the human's side (P2 players), SGATE = gate ? 1 + score tier
# : 0, RYU = the on-point object's form byte (Ryu's style, Mech Zangief), MVL = 0x80 when an assist object landed the KO.
# The other titles mapped to moves (Beetle traces work/achaudit tr9..tr12; web move lists): Eternal Slumber = Morrigan's
# level-3 LP,MK,b,MP,HK (0x4a); Ragnarok = Strider dp+PP (0x47; qcf+PP 0x35 is Ouroboros); Death Bite = Venom qcf+KK
# (0x3d; qcf+PP is Venom Web); Saotome Cyclone = Jin's tornado qcf+KK (0x39); Captain Beam (no move of that name) =
# Commando's beam hyper qcf+PP (0x34); Brilliant Shower = Lilith qcf+PP (0x3a); Sky Counter Crash = Shadow Lady's
# SPECIAL hcb+K flip kick (0x39, Chun-Li's Hazan Shu); Hulk Smash (no move of that name) = Orange Hulk's ground smash
# Gamma Quake qcf+KK (0x54); Iron Body = Zangief's Mech transform (b,d,db+KK): a win as Mech Zangief (form byte 2; its
# hypers leave +0x98 at 0).  Not mapped (set's rule kept): Magnetic Shockwave (PS1-only secret Mega Man hyper behind an
# unlock), Galaxy Energy (Onslaught: no move of that name; its two meter moves draw nothing recognisable).
MVL = V + 15
FIX = "--achfix" in sys.argv or os.environ.get("MVC_ACHFIX") == "1"
HYPER = {112473: (2, 0x3d, "Proton Cannon"), 112483: (40, 0x3e, "War Destroyer"), 112467: (18, 85, "Shinku Hadoken"),
         112476: (22, 64, "Kikosho"), 112468: (4, 96, "Hyper Charging Star"), 112470: (6, 79, "Gamma Wave"),
         112469: (10, 64, "Royal Flush"), 112474: (8, 65, "Berserker Barrage X"), 112482: (36, 0x3b, "Venom Web"),
         112486: (16, 0x4c, "Hyper Roll"), 112471: (14, 99, "Ultimate Web Throw"),
         112479: (30, 0x4a, "Eternal Slumber"), 112480: (28, 0x47, "Ragnarok"), 112472: (12, 0x3d, "Death Bite"),
         112477: (24, 0x39, "Saotome Cyclone"), 112475: (20, 0x34, "Captain Commando's beam hyper (qcf+PP)"),
         112484: (44, 0x3a, "Brilliant Shower"), 112487: (42, 0x39, "Sky Counter Crash"),
         112485: (38, 0x54, "Gamma Quake")}


def fix(a, mem, d):
    i = a["ID"]
    if 112467 <= i <= 112488:
        c = char_of(a["MemAddr"])
        if i in HYPER:
            assert HYPER[i][0] == c, i
            return f"{H(GATE)}=1_{H(ACT)}={c}_{H(MVL)}={0x80 | HYPER[i][1]}", "Defeat an opponent with " + HYPER[i][2] + d[d.index(" on difficulty"):]
        if i == 112481:
            return f"{H(GATE)}=1_{H(ACT)}={c}_{H(RYU)}=2", "Defeat an opponent as Mech Zangief (Iron Body)" + d[d.index(" on difficulty"):]
    if 112496 <= i <= 112498:          # score: SGATE = 1 + tier of the human side's score
        st = re.search(r"0xH07bdf2>(\d+)", a["MemAddr"]).group(1)
        return f"{H(SGATE)}>={i - 112496 + 2}_0xH07bdf2>{st}", d
    if i == 112491:                    # Overkill: after the human side's win, SELECT -> the winner hits again (0x7b84c 1 -> 2)
        return f"{H(MVL)}>=128_0xH07b740=0_0xH07bdc9<3_0xH07b84c=2", "Win a fight, then press SELECT to overkill"
    return mem, d


ACHS, MAP = [], []
for a in load():
    mem, cls, note = adapt(a)
    d = a["Description"].replace(" and with 3 rounds per match", "").replace(" (no Beginner mode)", "")
    d = d.replace("(no Beginner mode, Onslaught banned)", "(Onslaught banned)").replace(", Onslaught banned)", ")")
    if FIX: mem, d = fix(a, mem, d)
    ACHS.append(dict(id=a["ID"], points=a["Points"], title=a["Title"], desc=d, memaddr=mem))
    MAP.append((a["ID"], a["Title"], cls, note))

TEXT = dict(title="MvC (RA 11314, adapted)", title_cols=46, desc_cols=44, desc_lines=4, upper=True)

if __name__ == "__main__":
    import collections
    print(collections.Counter(c for _, _, c, _ in MAP))
