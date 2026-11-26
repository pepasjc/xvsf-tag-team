"""Where the external programs are.  Every tool takes them from here; nothing else in tools/ names a machine path.

    MIPS cross compiler prefix   XVSF_MIPS_PREFIX, else `mipsel-none-elf-gcc` on PATH, else local_paths.json
    chdman                       XVSF_CHDMAN, else `chdman` on PATH, else local_paths.json
    xdelta3                      XVSF_XDELTA, else `xdelta3` on PATH, else local_paths.json

local_paths.json (repository root, not committed; see local_paths.example.json): {"mips": prefix, "chdman": path,
"xdelta": path}, for a machine where the programs are not on PATH.

The compiler is only needed to rebuild our own MIPS code (tools/tagload, tools/nspdec, tools/ap8, tools/logo);
the prebuilt objects in the repository and the blob cache of builder/ cover the normal builds.
"""
import os, shutil

import json
_LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_paths.json")
_DEV = dict(mips="mipsel-none-elf-", chdman="chdman", xdelta="xdelta3")
if os.path.exists(_LOCAL):
    _DEV.update(json.load(open(_LOCAL)))


def mips_prefix():
    p = os.environ.get("XVSF_MIPS_PREFIX")
    if p: return p
    return "mipsel-none-elf-" if shutil.which("mipsel-none-elf-gcc") else _DEV["mips"]


def chdman():
    return os.environ.get("XVSF_CHDMAN") or shutil.which("chdman") or _DEV["chdman"]


def xdelta():
    return os.environ.get("XVSF_XDELTA") or shutil.which("xdelta3") or _DEV["xdelta"]
