"""DSM1 encoder: the MSHvSF "mid" sprite codec (format: common/dsp/dsm.py; decoder common/dsp/dsmdec.S).

Same model as XvSF XVM1: byte symbols, canonical Huffman (max 12 bits), table chosen by a clustered
(high nibble of the previous byte, byte above) context, 6-bit primary LUT + canonical fallback, copy-from-above /
repeat runs, escape.  The model sits at the start of the DSP pixel section (magic 'DSM1'); a tile stream is one
width byte, then the codes.  Tiles in `rle` keep their stock RLE streams, stored behind the DSM1 part.

A port of common/dsp/dsm.py encode() onto the batched kernels (xvb.kernels.xvm_parse_acc, xvb.xvm1 cluster /
make_model, mshb.kernels.dsm_emit / dsm_verify); it produces the same bytes.
"""
import struct
import numpy as np
from xvb import kernels as xk
from xvb.xvm1 import cluster, make_model, ESC, NS
from xvb.huff import RUNS, group_sum
from . import kernels as K
from .dspfile import assemble

MAGIC = 0x314D5344                          # 'DSM1'
MODEL_BITS = 16                             # tools/nsp_mid.py tab_lens default (XVM_MB unset)


def encode(x, k=64, pen=0, rle=(), passes=4, verify=True):
    """x: dspfile.DSP of a stock file -> (new file bytes, stats)"""
    x.decode_all(); rle = set(int(i) for i in rle)
    uniq = {}; order = []; where = {}
    for i in range(x.n):
        if i in rle: continue
        key = (int(x.wb[i]), x.raw(i))
        j = uniq.get(key)
        if j is None: j = uniq[key] = len(order); order.append(i)
        where[i] = j
    oi = np.array(order, np.int64)
    assert (x.wb[oi] < 256).all()
    sizes = x.nbytes[oi].astype(np.int64)
    offs = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    Ws = x.wb[oi].astype(np.int32)
    tot = int(offs[-1])
    S = np.frombuffer(b"".join(x.raw(i) for i in order), np.uint8).astype(np.int32)
    # context per byte: P = previous byte of the tile (255 at its start), U = byte above (255 in row 0)
    start = np.repeat(offs[:-1].astype(np.int64), sizes.astype(np.intp))
    pos = np.arange(tot, dtype=np.int64) - start
    wrep = np.repeat(Ws.astype(np.int64), sizes.astype(np.intp))
    P = np.where(pos > 0, np.concatenate([[255], S[:-1]]), 255)
    U = np.where(pos >= wrep, S[np.maximum(np.arange(tot, dtype=np.int64) - wrep, 0)], 255)
    ctx = ((P >> 4) << 8 | U).astype(np.int32)
    tmap = np.zeros(4096, np.int32)
    lens = np.zeros((1, NS), np.uint8); lens[0, :256] = 7; lens[0, 256:ESC] = 6; lens[0, ESC] = 8
    choice = np.zeros(tot, np.int32)
    for p in range(passes + 1):
        hist = np.zeros(4096 * NS, np.int32)
        tab = np.ascontiguousarray(tmap[ctx], np.int32)
        xk.xvm_parse_acc(S, offs, Ws, tab, ctx, np.ascontiguousarray(lens).reshape(-1), NS, RUNS, pen, choice, hist)
        hist = hist.reshape(4096, NS).astype(np.int64)
        if p == passes: break
        tmap, lens = cluster(hist, k, MODEL_BITS)
    used = np.nonzero(hist.sum(1))[0]
    th = group_sum(hist, used, tmap[used], lens.shape[0])
    assert not ((th[:, 256:ESC] > 0) & (lens[:, 256:ESC] == 0)).any() and (lens[:, ESC] > 0).all() and (lens[:, ESC] <= 8).all()
    model, codes = make_model(tmap, lens)
    model = bytearray(model); struct.pack_into("<I", model, 0, MAGIC)
    out = np.zeros(tot * 3 + len(order) * 8 + 16, np.uint8); ooffs = np.zeros(len(order) + 1, np.int32)
    m = K.dsm_emit(S, offs, Ws, tab, choice, RUNS, np.ascontiguousarray(lens).reshape(-1), NS,
                   np.ascontiguousarray(codes, np.int32).reshape(-1), out, ooffs)
    sec0 = bytearray(model) + out[:m].tobytes()
    uoff = ooffs[:len(order)].astype(np.int64) + len(model)
    sec0 += b"\0" * (4 + (-len(sec0) % 4))
    struct.pack_into("<I", sec0, 4, len(sec0))
    dsm_end = len(sec0)
    newoff = np.zeros(x.n, np.int64)
    for i, j in where.items(): newoff[i] = uoff[j]
    done = {}
    for i in range(x.n):                               # stock streams, in tile order, identical ones once
        if i in rle:
            o = int(x.off[i])
            st = x.sec[0][o:o + int(x.clen[i]) + 1]         # +1: an odd literal reads one byte past the stream
            if st not in done: done[st] = len(sec0); sec0 += st
            newoff[i] = done[st]
    sec0 += b"\0" * (-len(sec0) % 4)
    new = assemble(x, sec0, newoff)
    if verify:
        mem = np.frombuffer(bytes(sec0) + b"\0" * 16, np.uint8)
        raw = np.frombuffer(x._b, np.uint8)
        bad = K.dsm_verify(mem, dsm_end, newoff.astype(np.int32), x.nbytes, raw, x.ooff, np.zeros(1 << 17, np.uint8))
        assert bad == 0, "DSM1 round trip failed (%d)" % bad
    return new, dict(old=len(x.d), new=len(new), old_pix=x.sizes[0], new_pix=len(sec0), model=len(model),
                     tables=int(lens.shape[0]), dsm_part=dsm_end, rle_tiles=len(rle), tiles=x.n, uniq=len(order))
