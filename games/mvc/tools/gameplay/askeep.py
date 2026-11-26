"""ARCADE: the player's assist stays for the whole run (assist bugs lead, 2026-11-21; mktag.py `--askeep`, needs
--assistsel).

Bug (user, rc4.10, ARCADE P1, ASSIST MODE ROULETTE, no CONTINUE): partner Colossus for 4 matches, Cyclops from match 5.
Root cause: the ARCADE stage-screen setup (SEL01 0x8018ed64) calls stock 0x801909fc = "human side picks a special
partner on the stage screen": when the side's flag 0x8007cf68+0x1d (bit per side) is clear and the main object's byte
+0x2eb is 0 (cleared after every battle by the post-battle routine 0x8004c6cc, set to -1 only by a 3-button hold), it
sets the human's id 0x8007b8d8 / da = 0x10 (assist 4 = Cyclops) and spawns the special-partner object 0x801980f4(...,
0x600) again.  With the tag select the partner is chosen once in the select (assistsel.py), so this re-pick silently
replaced it with Cyclops (rc4.10 Beetle: work/asbug/asid.py, ROULETTE pick 5 -> 4 on the stage screen after fight 1;
NOP test keeps 5 through all 8 fights incl. Onslaught).  Found by nop-bisecting every id writer (work/asbug/rouobj4.py):
only SEL01 0x80190a74 (`sh 0x10, 0xb0(0x8007b828)`) changes P1's id.

Patch: 0x8018ed64 `jal 0x801909fc` -> nop (DAT/SEL01.ARC).  The CPU's assist is still re-rolled per opponent
(0x80047418, stage setup), one partner per opponent as the arcade does.  A CONTINUE is a rematch with the same picks
(no select, no stage screen), so the partner stays there too; a new game = new select = new pick.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from selscreen import FILE, BASE

SITE, STOCK = 0x8018ed64, 0x0C06427F            # jal 0x801909fc


def check_file(data):
    assert struct.unpack_from("<I", data, SITE - BASE)[0] == STOCK, f"{FILE} +{SITE - BASE:x}: not stock"


def overlay_patches():
    return [(FILE, SITE - BASE, bytes(4))]
