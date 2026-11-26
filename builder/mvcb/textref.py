"""Game words inside the frozen tool sources, stored as references to the user's disc.

Some MvC tool sources carry words of the game as text: the stock instructions a patch checks before it writes
(`0x27bdffe8, 0xafbf0010, ...`) or copies, and hex strings of stock bytes.  builder/data/mvc/tools must not carry them,
so snapshot() replaces every such run (the Option A rule: two consecutive non-trivial words equal to two aligned words
of a file of the disc, work/release12/optA_scan.py) by placeholders of the same length ("0x~~~~~~~~", "~~~~"), and
data/mvc/textref.json says where each run came from on the disc.  fill() writes the original text back from the user's
own files when the tool root is made, so the tools run byte for byte as they are in the repository.

    strip(text bytes, corpus)   -> (stripped bytes, [run, ...]) ; run = [kind, [token offsets], case, gameref segments]
    fill(stripped, runs, read)  -> original bytes
"""
import re
LIT = re.compile(rb"0x([0-9a-fA-F]{8})\b")
HEX = re.compile(rb"[0-9a-fA-F]{16,}")
GAP = re.compile(rb"[\s,()\[\]]*")


def _lit_runs(text):
    """runs of >= 2 consecutive 0xXXXXXXXX literals (optA_scan.literal_runs) -> [[match, ...], ...]"""
    out = []; cur = []; last = None
    for m in LIT.finditer(text):
        if last is not None and GAP.fullmatch(text[last:m.start()]): cur.append(m)
        else:
            if len(cur) >= 2: out.append(cur)
            cur = [m]
        last = m.end()
    if len(cur) >= 2: out.append(cur)
    return out


def _case(s):
    lo = s.lower() == s; up = s.upper() == s
    return "l" if lo else "u" if up else None


def strip(text, corpus):
    from xvb import gameref
    t = bytearray(text); runs = []
    for run in _lit_runs(bytes(text)):
        data = b"".join(int(m.group(1), 16).to_bytes(4, "little") for m in run)
        if not gameref.literal_runs(data, corpus): continue
        c = "".join(_case(m.group(1).decode()) or "m" for m in run)     # per token: l / u
        if "m" in c: raise ValueError("a mixed-case word literal")
        segs = gameref.encode(data, corpus)
        runs.append(["w", [m.start(1) for m in run], c, segs])
        for m in run: t[m.start(1):m.end(1)] = b"~" * 8
    for m in HEX.finditer(bytes(t)):
        h = m.group(0)[:len(m.group(0)) // 2 * 2]
        data = bytes.fromhex(h.decode())
        if not gameref.literal_runs(data, corpus): continue
        c = _case(h.decode()) or [i for i, ch in enumerate(h.decode()) if ch.isupper()]   # mixed: upper positions
        runs.append(["h", [m.start()], c, gameref.encode(data, corpus)])
        t[m.start():m.start() + len(h)] = b"~" * len(h)
    return bytes(t), runs


def fill(text, runs, read):
    from xvb import gameref
    t = bytearray(text)
    for kind, offs, case, segs in runs:
        data = gameref.resolve(segs, read)
        if kind == "w":
            for i, o in enumerate(offs):
                s = "%08x" % int.from_bytes(data[4 * i:4 * i + 4], "little")
                s = s.upper() if case[i] == "u" else s
                assert t[o:o + 8] == b"~" * 8
                t[o:o + 8] = s.encode()
        else:
            s = data.hex()
            if case == "u": s = s.upper()
            elif isinstance(case, list): s = "".join(ch.upper() if i in set(case) else ch for i, ch in enumerate(s))
            o = offs[0]
            assert t[o:o + len(s)] == b"~" * len(s)
            t[o:o + len(s)] = s.encode()
    return bytes(t)
