"""Build helpers for the MSHvSF speed modules.

    chunks(src_path, {name: (lo, hi)}, defs) -> ({name: bytes}, symbols)
A source split into chunks by lines `#@NAME`; each chunk is assembled at its own address with the symbols of the
other chunks defined as absolute values (fixed point; sizes do not depend on symbol values).  Asserts every chunk
fits its range and has no R3000 load-delay hazard (tools/speed/frame/hazard.py).
"""
import os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))   # repository root (games/mshvsf/tools/speed/ -> ../../../..)
sys.path.insert(0, os.path.join(ROOT, "tools", "speed", "frame")); sys.path.insert(0, os.path.join(ROOT, "tools"))
from gas import gas
import hazard


def split(src):
    out, cur = {}, None
    for line in src.splitlines():
        m = re.match(r"^#@(\w+)\s*$", line)
        if m: cur = m.group(1); out[cur] = ""; continue
        if cur: out[cur] += line + "\n"
    return out


def labels(text):
    return set(re.findall(r"^\s*([A-Za-z_]\w*):", text, re.M))


def chunks(path, ranges, defs=None):
    parts = split(open(path).read())
    assert set(parts) == set(ranges), (set(parts), set(ranges))
    own = {k: labels(v) for k, v in parts.items()}
    syms = {}
    for it in range(3):
        out = {}
        for k, text in parts.items():
            lo, hi = ranges[k]
            d = dict(defs or {})
            for k2, ls in own.items():
                if k2 != k:
                    for l in ls: d[l] = syms.get(l, ranges[k2][0])
            out[k], sy = gas(text, lo, d)
            for l in own[k]: syms[l] = sy[l]
    for k, (lo, hi) in ranges.items():
        assert lo + len(out[k]) <= hi, "chunk %s overflow: %d > %d" % (k, len(out[k]), hi - lo)
        bad = hazard.hazards(out[k], lo)
        assert not bad, "load-delay hazards in %s: %s" % (k, bad)
    return out, syms


def pieces(text):
    """split a source into functions at lines '# -----' -> {first label: text}"""
    hdr, *funcs = re.split(r"(?m)^(?=# -{20,} )", text)
    return {re.search(r"(?m)^(\w+):", f).group(1): f for f in funcs}


def pack(text, ranges, defs=None, fixed=None):
    """place the pieces of `text` (see pieces) into `ranges` {name: (lo, hi)} first-fit-decreasing (fixed: {piece:
    range name}) and assemble -> ({name: bytes}, symbols, plan).  Pieces must reference each other only by j / jal /
    la (no conditional branch between pieces)."""
    import tempfile
    P = pieces(text)
    lab = {k: labels(v) for k, v in P.items()}
    allab = set().union(*lab.values())
    size = {}
    for k, v in P.items():
        d = dict(defs or {}); d.update({l: 0x80021234 for l in allab - lab[k]})
        size[k] = len(gas(v, 0x80020000, d)[0])
    fixed = fixed or {}
    free = {k: hi - lo for k, (lo, hi) in ranges.items()}
    plan = {k: [] for k in ranges}
    for f in sorted(P, key=lambda f: (f not in fixed, -size[f])):
        ks = [fixed[f]] if f in fixed else sorted(free, key=lambda k: free[k])
        k = next((k for k in ks if free[k] >= size[f]), None)
        assert k, "no room for %s (%d bytes): %s" % (f, size[f], free)
        plan[k].append(f); free[k] -= size[f]
    plan = {k: v for k, v in plan.items() if v}
    src = os.path.join(tempfile.mkdtemp(), "packed.S")
    open(src, "w").write("".join("#@%s\n" % k + "".join(P[f] for f in fs) for k, fs in plan.items()))
    out, syms = chunks(src, {k: ranges[k] for k in plan}, defs)
    return out, syms, plan
