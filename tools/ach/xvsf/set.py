"""XvSF built-in achievement set.  RetroAchievements has no set for X-Men vs. Street Fighter (PS1, game 16316:
0 achievements on 2026-11-16), so this one is our own, written for the tag hack ("similar" set: arcade clears,
one per character, the tag rules, combos).  Conditions are rcheevos syntax over the derived bytes of port.c
(struct vars at V = ACH_BASE + 0x20); tools/ach/host/diff.c checks the compiled tables against rcheevos.
"""
V = 0x00f060                      # ach_v = achbuild.SPAN_BASE + 0x20 (rcheevos address)
SIDE, TEAM, ACT, ACTP, COMBO, KOS, FULL, WINS, CLEAR, ALIVE, MODE, RUNOK, VSWINS = (
    V + 0, V + 1, V + 4, V + 5, V + 6, V + 7, V + 8, V + 9, V + 10, V + 11, V + 12, V + 13, V + 14)
H = lambda a: "0xH%06x" % a
D = lambda a: "d0xH%06x" % a


def team_has(cid):
    return "0x%s%06x=1" % ("MNOPQRST"[cid % 8], TEAM + cid // 8)


NAMES = [(0, "Wolverine"), (1, "Cyclops"), (2, "Storm"), (3, "Rogue"), (4, "Gambit"), (5, "Sabretooth"),
         (6, "Juggernaut"), (7, "Magneto"), (9, "Ryu"), (10, "Ken"), (11, "Chun-Li"), (12, "Dhalsim"),
         (13, "Zangief"), (14, "M. Bison"), (15, "Akuma"), (16, "Charlie"), (17, "Cammy")]
TITLES = {0: "Berserker Barrage", 1: "Optic Victory", 2: "Weather the Storm", 3: "Southern Belle Brawl",
          4: "Raise the Stakes", 5: "Feral Instinct", 6: "Unstoppable", 7: "Master of Magnetism",
          9: "Heart of Battle", 10: "Shoryuken Showboat", 11: "Spinning Bird Champion",
          12: "Yoga Inferno", 13: "Red Cyclone", 14: "Psycho Crusher", 15: "Raging Demon",
          16: "Sonic Boom Salute", 17: "Delta Red Mission"}
CLEAR_OK = f"{H(CLEAR)}=1"
ACHS = []


def ach(i, pts, title, desc, mem):
    ACHS.append(dict(id=i, points=pts, title=title, desc=desc, memaddr=mem))


ach(1, 10, "Children of the Atom", "Beat Apocalypse in Arcade mode", CLEAR_OK)
for k, (cid, name) in enumerate(NAMES):
    alt = ""
    if cid == 11:                                   # the alternate Chun-Li id 18 counts too
        alt = f"S{team_has(11)}S{team_has(18)}"
        mem = CLEAR_OK + alt
    else:
        mem = f"{CLEAR_OK}_{team_has(cid)}"
    ach(10 + k, 5, TITLES[cid], f"Arcade clear with {name}", mem)
ach(2, 25, "Flawless Crossover", "Arcade clear, no fight lost", f"{CLEAR_OK}_{H(RUNOK)}=1")
ach(3, 10, "Apocalypse Averted", "Beat Apocalypse, both standing", f"{CLEAR_OK}_{H(ALIVE)}=2")
ach(4, 10, "Dream Team", "Arcade clear: X-Man + SF team",
    f"{CLEAR_OK}_{H(TEAM)}!=0S{H(TEAM + 1)}>=2S{H(TEAM + 2)}!=0")
ach(5, 5, "Tag, You're It", "KO a foe with your 2nd pick",
    f"{H(SIDE)}>0_{H(ACTP)}=1_{H(KOS)}>{D(KOS)}")
ach(6, 10, "Perfect Partners", "Win, both at full life",
    f"{H(SIDE)}>0_{H(FULL)}=1_{H(WINS)}>{D(WINS)}")
# (ach audit 2026-11-21, env XVSF_ACHFIX=1, not in 1.3): ALIVE=1 alone also takes a win after losing the 2nd pick; the
# survivor on point being the 2nd pick (ACTP) = the 1st pick fell.  Default (released) set unchanged.
ach(7, 5, "Last One Standing", "Win after losing your 1st pick",
    f"{H(SIDE)}>0_{H(ALIVE)}=1_{H(WINS)}>{D(WINS)}" + (f"_{H(ACTP)}=1" if __import__("os").environ.get("XVSF_ACHFIX") == "1" else ""))
ach(8, 5, "Combo Rookie", "10-hit combo", f"{H(SIDE)}>0_{H(COMBO)}>=10")
ach(9, 10, "Combo Expert", "20-hit combo", f"{H(SIDE)}>0_{H(COMBO)}>=20")
ach(30, 25, "Infinite Combo", "35-hit combo", f"{H(SIDE)}>0_{H(COMBO)}>=35")
ach(31, 5, "Rival Showdown", "Beat a player in Versus mode", f"{H(VSWINS)}!={D(VSWINS)}")

TEXT = dict(title="XvSF tag hack set", title_cols=24, desc_cols=31, desc_lines=2, upper=True)
