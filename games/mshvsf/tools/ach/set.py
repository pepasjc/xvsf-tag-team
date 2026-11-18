"""MSHvSF built-in achievement set: RetroAchievements game 16340 ("Marvel Super Heroes vs. Street Fighter",
46 achievements by the set's authors, unofficial / not yet published on the site), adapted to the tag hack.

The conditions read the derived bytes of port.c (struct vars at V = ACH_BASE + 0x20) plus a few game bytes; the
mapping from the original conditions is in docs/ACHIEVEMENTS.md (keep / remap / adapt per achievement).
ACHS feeds tools/ach/setc.py; ORIG keeps the original condition strings for the record.
"""
V = 0x00f060                      # ach_v = achbuild.SPAN_BASE + 0x20 (rcheevos address)
SIDE, TEAM, ACT, ACTP, COMBO, KOS, FULL, WINS, CLEAR, BOSS, DIFF, MODE, RUNOK = (
    V + 0, V + 1, V + 5, V + 6, V + 7, V + 8, V + 9, V + 10, V + 11, V + 12, V + 13, V + 14, V + 15)
STAGE = 0x0707c4                  # arcade stage (0 first fight .. 7 Cyber-Akuma; 8 after the last win)

H = lambda a: "0xH%06x" % a
D = lambda a: "d0xH%06x" % a


def team_has(cid2):
    n = cid2 // 2
    return "0x%s%06x=1" % ("MNOPQRST"[n % 8], TEAM + n // 8)


NAMES = {0x12: "Ryu", 0x14: "Ken", 0x24: "Dan", 0x16: "Chun-Li", 0x1e: "Akuma", 0x20: "Sakura", 0x1a: "Zangief",
         0x1c: "M. Bison", 0x18: "Dhalsim", 0x02: "Cyclops", 0x0e: "Spider-Man", 0x04: "Captain America",
         0x0a: "Shuma-Gorath", 0x08: "Wolverine", 0x06: "Hulk", 0x10: "Blackheart", 0x0c: "Omega Red",
         0x32: "Armored Spider-Man", 0x2a: "Evil Sakura", 0x28: "Mech-Zangief", 0x30: "Mephisto", 0x2c: "Shadow",
         0x2e: "U.S. Agent", 0x26: "Cyber-Akuma", 0x00: "Apocalypse"}

CLEAR_OK = f"{H(CLEAR)}=1_{H(DIFF)}=1"
ACHS = []


def ach(i, pts, title, desc, mem, how):
    ACHS.append(dict(id=i, points=pts, title=title, desc=desc, memaddr=mem, how=how))


ach(561734, 5, "Tag-Team Troublemaker", "KO an opponent with your second character on point",
    f"{H(SIDE)}>0_{H(ACTP)}=1_{H(KOS)}>{D(KOS)}", "remap: on-point flag P1 obj +0x143 and the KO of either opponent object")
ach(561735, 5, "Untouchable Force", "Win a fight with both of your characters at full life (default or higher difficulty)",
    f"{H(DIFF)}=1_{H(FULL)}=1_{H(WINS)}>{D(WINS)}", "adapt: single round -> the win, both team members at full life")
ach(561736, 50, "Lossless Multiversal Clear", "Finish Arcade mode without losing a fight (default or higher difficulty)",
    f"{CLEAR_OK}_{H(RUNOK)}=1",
    "adapt: single round -> no lost fight (no continue) from the first stage on (port.c run_ok)")
ach(561737, 25, "Total Annihilation Pushed Back Another Day", "Defeat Cyber-Akuma (default or higher difficulty)",
    f"{CLEAR_OK}_{H(BOSS)}=38", "remap: the last arcade win against Cyber-Akuma")
TITLES = {561738: "Wanderer of the Hadouken", 561739: "Blonde Ambition: Fire Edition", 561740: "Master of the Saikyo Struggle",
          561741: "Kicking First, Questions Later", 561742: "The Art of Zenmetsu", 561743: "Honor Student of Street Fighting",
          561744: "Suplex the Earth", 561745: "Psycho Power Paradise", 561746: "Yoga Around the World",
          561747: "Visor Violence", 561748: "Friendly Neighborhood Deconstructor", 561749: "Stars, Stripes, and Smackdowns",
          561750: "Single-Eyed Superiority", 561751: "Man Made Me a World-Wide Weapon", 561752: "Rampage World Tour",
          561753: "Demonic Duties Fulfilled", 561754: "Cold War, Warm Blood",
          561772: "I Actually Feel Pretty Good, Mister Stark", 561773: "Extra Credit: Corruption 101",
          561774: "Jet Fuel Doesn't Melt Soviet Steel", 561775: "Devil in the Details", 561776: "Shadaloo's Experiment: Success",
          561777: "John Walker's Redemption", 561778: "Shining Circuit Gou Rocket Punch Man", 561779: "The First Mutant Ascends"}
FINISH = [(561738, 0x12), (561739, 0x14), (561740, 0x24), (561741, 0x16), (561742, 0x1e), (561743, 0x20), (561744, 0x1a),
          (561745, 0x1c), (561746, 0x18), (561747, 0x02), (561748, 0x0e), (561749, 0x04), (561750, 0x0a), (561751, 0x08),
          (561752, 0x06), (561753, 0x10), (561754, 0x0c)]
for i, c in FINISH:
    ach(i, 10, TITLES[i], f"Finish Arcade mode with {NAMES[c]} on your team (default or higher difficulty)",
        f"{CLEAR_OK}_{team_has(c)}", "remap: stage 7 -> 8 (last win) with the character in the human team (main or partner)")
# combos: the set's counter (0x0707b6) is the opponent's life bar, not a hit count; the real combo count is the
# attacker object's +0x114.  The set's 50/40/30-hit targets are cut to 20/16/12 (MSHvSF combos rarely pass 20).
COMBOS = [(561755, 0x12, 50, "My Journey Has No End, But 20 Will Suffice"), (561756, 0x14, 50, "Flame Cascade Finale"),
          (561757, 0x24, 50, "Short Range Hadouken Hit Faster"), (561758, 0x16, 50, "Fastest Feet in the Multiverse"),
          (561759, 0x1e, 50, "Combo No Jutsu: Destruction Style"), (561760, 0x20, 30, "After-School Beatdown Club"),
          (561761, 0x1a, 30, "Cyclone Compression Therapy"), (561762, 0x1c, 30, "Psycho Combo-nation"),
          (561763, 0x18, 30, "Average 12-Move Yoga Routine"), (561764, 0x02, 30, "Optic Blast-tacular"),
          (561765, 0x0e, 40, "Webbing Together 16 Consecutive Regrets"), (561766, 0x04, 30, "Liberty, Justice, and American Juggles"),
          (561767, 0x0a, 40, "Tentacular Spectacular"), (561768, 0x08, 40, "No Healing Factor Needed"),
          (561769, 0x06, 40, "Hulk Smash!! 16 Smash!!"), (561770, 0x10, 30, "Twelve Measures of Malevolence"),
          (561771, 0x0c, 30, "Carbonadium Catastrophe")]
CUT = {50: 20, 40: 16, 30: 12}
for i, c, n, t in COMBOS:
    m = CUT[n]
    ach(i, 5, t, f"Perform a {m}-hit combo with {NAMES[c]}", f"{H(ACT)}={c}_{H(COMBO)}>={m}",
        f"remap+adapt: hit count of the human's on-point object (+0x114), target {n} -> {m}")
for i, c in [(561772, 0x32), (561773, 0x2a), (561774, 0x28), (561775, 0x30), (561776, 0x2c), (561777, 0x2e),
             (561778, 0x26), (561779, 0x00)]:
    ach(i, 10, TITLES[i], f"Finish Arcade mode with {NAMES[c]} on your team (default or higher difficulty)",
        f"{CLEAR_OK}_{team_has(c)}", "remap: as above (secret character)")

TEXT = dict(title="MSHvSF (RA 16340, adapted)", title_cols=43, desc_cols=43, desc_lines=4, upper=True)
