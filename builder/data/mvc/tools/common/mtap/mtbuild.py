"""Build common/mtap/mtcore.c for one game: compile with the game's mtgame.h, pack every function / object into the
game's free spans (first fit, largest first), link.  -> dict(segs=[(addr, bytes)], sym={...}, used, free)

The spans are EXE ranges (written into the executable on the disc: no boot copy, no kernel RAM).
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "tools")))

CF = ["-Os", "-G0", "-mips1", "-mno-abicalls", "-fno-pic", "-ffreestanding", "-nostdlib", "-msoft-float",
      "-fno-builtin", "-ffunction-sections", "-fdata-sections", "-fno-merge-constants", "-fno-toplevel-reorder"]


def run(args, cwd):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("mtbuild: %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout


def build(game_dir, spans, out_dir, defines=None, keep=("mt_tick", "mt_mask", "mt_mask_v")):
    import toolenv
    gcc = toolenv.mips_prefix()
    os.makedirs(out_dir, exist_ok=True)
    D = ["-D%s=%s" % kv for kv in (defines or {}).items()]
    run([gcc + "gcc"] + CF + ["-I" + game_dir] + D + ["-c", os.path.join(HERE, "mtcore.c"), "-o", "mtcore.o"], out_dir)
    ent = " ".join("KEEP(*(%s))" % k if k.startswith(".") else "KEEP(*(.text.%s))" % k for k in keep)   # (".sec": a whole section name)
    open(os.path.join(out_dir, "p1.ld"), "w").write("SECTIONS { . = 0x80000000; .all : { %s *(.text*) *(.rodata*) *(.data*) *(.bss*) *(COMMON) } "
                                                    "/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) } }" % ent)
    r = subprocess.run([gcc + "ld", "--gc-sections", "--print-gc-sections", "-T", "p1.ld", "-o", "p1.elf", "mtcore.o"],
                       cwd=out_dir, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    gone = {l.split("'")[1] for l in r.stderr.splitlines() if "removing unused section" in l}
    secs = []
    for l in run([gcc + "objdump", "-h", "mtcore.o"], out_dir).splitlines():
        p = l.split()
        if len(p) >= 7 and p[0].isdigit():
            name, size, al = p[1], int(p[2], 16), 2 ** int(p[6].split("**")[1])
            if size and name not in gone and name.startswith((".text", ".rodata", ".data", ".bss", ".sbss", ".sdata")):
                secs.append((name, size, max(al, 4)))
    total = sum(s for _, s, _ in secs)
    room = [[sp[0], sp[1]] for sp in spans]
    tag = [sp[2] if len(sp) > 2 else "" for sp in spans]       # tagged span: only sections whose name has the tag
    place = [[] for _ in spans]
    for name, size, al in sorted(secs, key=lambda x: -x[1]):
        for i, rr in enumerate(room):
            want = next((t for t in tag if t and t in name), "")    # the section's tag ("" = untagged)
            if tag[i] != want: continue
            st = (rr[0] + al - 1) & ~(al - 1)
            if st + size <= rr[1]:
                place[i].append(name); rr[0] = st + size; break
        else:
            raise SystemExit("mtap does not fit the spans: %s %d bytes (all %d, spans %d)" % (name, size, total, sum(sp[1] - sp[0] for sp in spans)))
    body = " ".join(" .s%d 0x%08x : { %s . = ALIGN(4); }" % (i, a, " ".join("KEEP(mtcore.o(%s))" % n for n in place[i]))
                    for i, (a, b) in enumerate([sp[:2] for sp in spans]))
    open(os.path.join(out_dir, "mt.ld"), "w").write("SECTIONS { %s /DISCARD/ : { *(*) } }" % body)
    run([gcc + "ld", "-T", "mt.ld", "-o", "mt.elf", "mtcore.o"], out_dir)
    segs = []
    for l in run([gcc + "objdump", "-h", "mt.elf"], out_dir).splitlines():
        p = l.split()
        if len(p) >= 4 and p[1].startswith(".s") and p[1][2:].isdigit():
            size, vma = int(p[2], 16), int(p[3], 16)
            if not size: continue
            run([gcc + "objcopy", "-O", "binary", "--set-section-flags", "%s=alloc,load,contents" % p[1], "-j", p[1], "mt.elf", p[1][1:] + ".bin"], out_dir)
            data = open(os.path.join(out_dir, p[1][1:] + ".bin"), "rb").read()
            data += bytes(size - len(data)) + bytes(-size % 4)
            segs.append((vma, data))
    sym = {}
    for l in run([gcc + "nm", "-n", "mt.elf"], out_dir).splitlines():
        p = l.split()
        if len(p) == 3: sym[p[2]] = int(p[0], 16) & 0xFFFFFFFF
    for a, d in segs:
        assert any(sp[0] <= a and a + len(d) <= sp[1] for sp in spans), "segment %08x+%x outside the spans" % (a, len(d))
    used = sum(len(d) for _, d in segs)
    return dict(segs=segs, sym=sym, used=used, free=sum(sp[1] - sp[0] for sp in spans) - used, total=total,
                place={hex(spans[i][0]): place[i] for i in range(len(spans))})


def jal(t): return 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
def j(t): return 0x08000000 | ((t >> 2) & 0x03FFFFFF)
