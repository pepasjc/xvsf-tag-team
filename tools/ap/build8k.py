"""build8.py with EXTRA keep-stock entries from a file, for content variants measured on the built disc (work/ap/SPEC.md section 19).
aplib.KEEP_STOCK and dirbuild.KEEP_STOCK themselves are not changed: the frozen directories keep rebuilding bit for bit with build8.py.

    python build8k.py --keep-file KEEP.json  <every argument of build8.py>

KEEP.json: {"body": {"<character>": [[group, index], ...]}, "direct": {"<character>": [overlay offset of the animation's first record, ...]},
           "unkeep": {"<character>": [[group, index], ...]} (removed from aplib.KEEP_STOCK)}
Nothing here is derived from either game; the keep file holds only animation numbers."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aplib, dirbuild, build8


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    i = argv.index("--keep-file"); k = json.load(open(argv[i + 1])); del argv[i:i + 2]
    for c, L in k.get("body", {}).items():
        cur = aplib.KEEP_STOCK.setdefault(int(c), [])
        for g, j in L:
            if (g, j) not in cur: cur.append((g, j))
    for c, L in k.get("direct", {}).items():
        cur = dirbuild.KEEP_STOCK.setdefault(int(c), [])
        for o in L:
            if int(o) not in cur: cur.append(int(o))
    for c, L in k.get("unkeep", {}).items():          # 1.4: animations taken OFF aplib.KEEP_STOCK (restored; the 8 MB tile cache absorbs them)
        cur = aplib.KEEP_STOCK.get(int(c), [])
        for g, j in L:
            if (g, j) in cur: cur.remove((g, j))
    print("extra keep-stock:", json.dumps(k))
    sys.argv = [sys.argv[0]] + argv
    return build8.main()


if __name__ == "__main__":
    sys.exit(main())
