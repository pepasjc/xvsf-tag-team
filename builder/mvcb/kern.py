"""Kernels of the MvC tier codecs (the encoders' own numba functions; the browser installs JavaScript twins here).

From tools/nsp_huff.py (parse2), tools/nsp_mid.py (parse, tile_ctx, make_model), tools/nsp_codec.py (canon, RUNS),
common/dsp/dsh.py (enc_tile, ref_decode, header, tile_ctx), common/dsp/dsm.py (emit, ref_decode), common/dsp/dsa.py
(PAIRS) and games/mvc/tools/codec2/dsr.py (tile_decisions, rc_encode, ref_decode; loaded from the tool root).
"""
import os, sys, importlib.util
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(REPO, "tools"), os.path.join(REPO, "common", "dsp")):
    if p not in sys.path: sys.path.insert(0, p)
import nsp_codec as _NC                     # noqa: E402
import nsp_huff as _XH                      # noqa: E402
import nsp_mid as _XM                       # noqa: E402
import dsh as _H                            # noqa: E402
import dsm as _M                            # noqa: E402
import dsa as _A                            # noqa: E402

NR = _NC.NR
R16 = _NC.RUNS.astype(np.int64)
R64 = R16
NS_H = 16 + NR
NS_M = _XM.NS
PAIRS = np.array(_A.PAIRS, np.int64)

parse2 = _XH.parse2
dsh_enc_tile = _H.enc_tile
dsh_ref_decode = _H.ref_decode


def dsh_header(W, e, rep): return _H.header(W, e, rep, 1)


def dsh_tile_ctx(w, wb): return _H.tile_ctx(w, wb)


def canon_codes(lens): return _NC.canon(lens)[0]


dsm_parse = _XM.parse
dsm_emit = _M.emit
dsm_ref_decode = _M.ref_decode
dsm_tile_ctx = _XM.tile_ctx


def dsm_make_model(tmap, lens):
    m, codes = _XM.make_model(tmap, lens)
    m = bytearray(m); m[0:4] = (0x314D5344).to_bytes(4, "little")
    return bytes(m)


_dsr = None


def _load_dsr():
    global _dsr
    if _dsr is None:
        p = os.environ.get("MVCB_DSR") or os.path.join(REPO, "games", "mvc", "tools", "codec2", "dsr.py")
        spec = importlib.util.spec_from_file_location("mvcb_dsr", p); m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m); _dsr = m
    return _dsr


def dsr_tile_decisions(*a): return _load_dsr().tile_decisions(*a)
def dsr_rc_encode(*a): return _load_dsr().rc_encode(*a)
def dsr_ref_decode(*a): return _load_dsr().ref_decode(*a)
