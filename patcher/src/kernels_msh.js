/* Hot loops of the MSHvSF sprite encoders (DSM1, DSH1) - the JavaScript twin of builder/mshb/kernels.py.
 *
 * Pyodide has no numba, so the browser build runs these instead of the compiled Python kernels; the shared
 * pieces (parses, hufflens_many, argsort_np, cost_argmin) are XVK in kernels.js.  Every function mirrors the
 * Python function of the same name line by line (same arguments, same flat typed arrays, same integer
 * arithmetic).  All values fit 32 bits.
 *
 * Arrays arrive as typed-array VIEWS of the numpy arrays (no copies): Int32Array for int32, Uint8Array for uint8.
 * Python side: mshb.kernels.use_js(MSK.forPyodide(), XVK.forPyodide()).
 */
"use strict";
const MSK = (() => {

  // ---------------------------------------------------------------- stock RLE (game decoder 0x8001bd68)
  function dsp_rle_all(mem, base, toff, tn, out, ooff, clen, wlen) {
    for (let i = 0; i < toff.length; i++) {
      let p = base + toff[i], k = 0, extra = 0;
      const n = tn[i], o = ooff[i];
      while (k < n) {
        const b = mem[p++];
        if (b & 0xF0) {
          const v = (b & 15) * 0x11, c = (b >> 4) + 1;
          for (let j = 0; j < c; j++) out[o + k++] = v;
          extra = 0;
        } else {
          const c = (b & 15) + 1;
          for (let j = 0; j < c; j++) out[o + k++] = mem[p + j];
          p += c; extra = c & 1;
        }
      }
      clen[i] = p - base - toff[i];
      if (extra) out[o + k++] = mem[p];
      wlen[i] = k;
    }
    return 0;
  }

  function rle_n(mem, pos, n, out) {
    let p = pos, k = 0;
    while (k < n) {
      const b = mem[p++];
      if (b & 0xF0) {
        const v = (b & 15) * 0x11, c = (b >> 4) + 1;
        for (let j = 0; j < c; j++) { if (k < n) out[k] = v; k++; }
      } else {
        const c = (b & 15) + 1;
        for (let j = 0; j < c; j++) { if (k < n) out[k] = mem[p + j]; k++; }
        p += c;
      }
    }
    return p - pos;
  }

  function rle_written(mem, pos, n, out) {
    let p = pos, k = 0, extra = 0;
    while (k < n) {
      const b = mem[p++];
      if (b & 0xF0) {
        const v = (b & 15) * 0x11, c = (b >> 4) + 1;
        for (let j = 0; j < c; j++) out[k++] = v;
        extra = 0;
      } else {
        const c = (b & 15) + 1;
        for (let j = 0; j < c; j++) out[k++] = mem[p + j];
        p += c; extra = c & 1;
      }
    }
    if (extra) out[k++] = mem[p];
    return k;
  }

  // ---------------------------------------------------------------- DSM1 (byte symbols)
  function dsm_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, out, ooffs) {
    const NRr = RUNS.length, ESC = 256 + 2 * NRr;
    let p = 0;
    for (let ti = 0; ti < Ws.length; ti++) {
      const b = offs[ti], n = offs[ti + 1] - b, W = Ws[ti];
      ooffs[ti] = p;
      out[p++] = W;
      let acc = 0, nb = 0, i = 0;
      while (i < n) {
        const t = tab[b + i] * NS, c = choice[b + i];
        let raw = -1, sym;
        if (c === 0) {
          sym = S[b + i]; i++;
          if (lens[t + sym] === 0) { raw = sym; sym = ESC; }
        } else { sym = 255 + c; i += RUNS[(c - 1) % NRr]; }
        const l = lens[t + sym];
        acc = (acc << l) | codes[t + sym]; nb += l;
        if (raw >= 0) { acc = (acc << 8) | raw; nb += 8; }
        while (nb >= 8) { out[p++] = (acc >> (nb - 8)) & 255; nb -= 8; }
        acc &= (1 << nb) - 1;
      }
      if (nb) out[p++] = (acc << (8 - nb)) & 255;
    }
    return p;
  }

  function dsm_ref_decode(mem, src, n, model, out) {
    const fbo = model + (mem[model + 8] | (mem[model + 9] << 8));
    const W = mem[src];
    let buf = ((mem[src + 1] << 24) | (mem[src + 2] << 16) | (mem[src + 3] << 8) | mem[src + 4]) >>> 0;
    const src0 = src; src += 5;
    let c = 16, P = 255, ph = 15 << 8, o = 0;
    while (o < n) {
      const U = o >= W ? out[o - W] : 255;
      const t = mem[model + 76 + (ph | U)];
      let a = model + 4172 + (t << 7) + ((buf >>> 25) & 0x7e);
      let e = mem[a] | (mem[a + 1] << 8);
      if ((e & 0xC000) === 0xC000) {
        const w = buf >>> 20;
        let p = fbo + (t << 5), sh = 5;
        for (;;) {
          const lim = mem[p] | (mem[p + 1] << 8);
          if (w < lim) break;
          p += 4; sh--;
        }
        let adj = mem[p + 2] | (mem[p + 3] << 8);
        if (adj & 0x8000) adj -= 0x10000;
        a = model + adj + ((w >> sh) << 1);
        e = mem[a] | (mem[a + 1] << 8);
      }
      const l = e & 15;
      buf = (buf << l) >>> 0; c -= l;
      if (e & 0x8000) {
        if (e & 0x1000) {
          P = buf >>> 24;
          buf = (buf << 8) >>> 0; c -= 8;
          out[o++] = P;
        } else {
          a = model + 12 + ((e >> 3) & 0x3e);
          const r = mem[a] | (mem[a + 1] << 8);
          if (e & 0x2000) { for (let k = 0; k < r; k++) out[o++] = P; }
          else {
            for (let k = 0; k < r; k++) { out[o] = o >= W ? out[o - W] : 255; o++; }
            P = out[o - 1];
          }
        }
      } else { P = (e >> 4) & 255; out[o++] = P; }
      ph = (P >> 4) << 8;
      if (c < 0) {
        const v = (mem[src] << 8) | mem[src + 1];
        buf = (buf | (v << (-c))) >>> 0;
        src += 2; c += 16;
      }
    }
    return src - src0;
  }

  function dsm_verify(mem, end, woff, tn, raw, roff, scratch) {
    let bad = 0;
    for (let i = 0; i < woff.length; i++) {
      const n = tn[i];
      if (woff[i] >= end) rle_n(mem, woff[i], n, scratch);
      else {
        const used = dsm_ref_decode(mem, woff[i], n, 0, scratch);
        if (woff[i] + used > end) return -1 - i;
      }
      const r = roff[i];
      for (let k = 0; k < n; k++) if (scratch[k] !== raw[r + k]) { bad++; break; }
    }
    return bad;
  }

  // ---------------------------------------------------------------- DSH1 (pixel symbols)
  function dsh_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, hv, hl, tail, toff, out, ooffs) {
    let p = 0;
    for (let ti = 0; ti < Ws.length; ti++) {
      const b = offs[ti], n = offs[ti + 1] - b;
      ooffs[ti] = p;
      let acc = hv[ti], nb = hl[ti], i = 0;
      while (i < n) {
        const t = tab[b + i] * NS, c = choice[b + i];
        let sym;
        if (c === 0) { sym = S[b + i]; i++; }
        else { sym = 15 + c; i += RUNS[c - 1]; }
        const l = lens[t + sym];
        acc = (acc << l) | codes[t + sym]; nb += l;
        while (nb >= 8) { out[p++] = (acc >> (nb - 8)) & 255; nb -= 8; }
        acc &= (1 << nb) - 1;
      }
      for (let k = toff[ti]; k < toff[ti + 1]; k++) {
        acc = (acc << 8) | tail[k];
        out[p++] = (acc >> nb) & 255;
        acc &= (1 << nb) - 1;
      }
      if (nb) out[p++] = (acc << (8 - nb)) & 255;
    }
    return p;
  }

  function dsh_ref_decode(mem, src, n, model, RUNS, out, rb) {
    for (let i = 0; i < 260; i++) rb[i] = 15;
    const src0 = src;
    const m1 = model + 12 + 2 * (mem[model + 10] | (mem[model + 11] << 8));
    let buf = 0, nbits = 0, v = 0, k = 0, wc = 0;
    for (;;) {
      if (nbits === 0) { buf = mem[src++]; nbits = 8; }
      nbits--; v = v * 2 + ((buf >> nbits) & 1); k++;
      if ((k === 1 && v === 0) || (k === 2 && v === 2)) { wc = v >> 1; break; }
      if (k === 6) { wc = v & 15; break; }
    }
    const W = (wc + 1) * 16;
    v = 0; k = 0;
    let rep = 0, e = 0;
    for (;;) {
      if (nbits === 0) { buf = mem[src++]; nbits = 8; }
      nbits--; v = v * 2 + ((buf >> nbits) & 1); k++;
      if (k === 2 && v === 2) { e = 0; break; }
      if (k === 5 && (v >> 4) === 0) { e = v & 15; rep = 1; break; }
      if (k === 6) { e = v & 15; break; }
    }
    let x = 0, L = 15, UL = 15, lo = 0, o = 0, run = 0;
    while (o < n) {
      const U = rb[x];
      let p;
      if (run === 0) {
        const c1 = mem[m1 + ((L << 8) | (U << 4) | UL)];
        const t = mem[m1 + 4096 + ((c1 << 4) | rb[x + 1])];
        let sp = model + (mem[model + 12 + 2 * t] | (mem[model + 13 + 2 * t] << 8));
        let rec = sp - 1, d = 0;
        for (;;) {
          if (nbits === 0) { buf = mem[src++]; nbits = 8; }
          nbits--;
          d = d * 2 + ((buf >> nbits) & 1);
          const c = mem[rec--];
          if (d < c) break;
          d -= c; sp += c;
        }
        const sym = mem[sp + d];
        if (sym < 16) p = sym;
        else { run = RUNS[sym - 16] - 1; p = U; }
      } else { run--; p = U; }
      rb[x] = p;
      if (x & 1) out[o++] = lo | (p << 4);
      else lo = p;
      x++;
      if (x === W) { x = 0; L = 15; UL = 15; }
      else { L = p; UL = U; }
    }
    if (rep) { for (let j = 0; j < e; j++) out[n + j] = out[n - 1]; }
    else {
      for (let j = 0; j < e; j++) {
        v = 0;
        for (let q = 0; q < 8; q++) {
          if (nbits === 0) { buf = mem[src++]; nbits = 8; }
          nbits--; v = v * 2 + ((buf >> nbits) & 1);
        }
        out[n + j] = v;
      }
    }
    return [n + e, src - src0];
  }

  function dsh_verify(mem, end, woff, tn, want, wofs, RUNS, scratch, rb) {
    let bad = 0;
    for (let i = 0; i < woff.length; i++) {
      const n = tn[i];
      let m;
      if (woff[i] >= end) m = rle_written(mem, woff[i], n, scratch);
      else {
        const r = dsh_ref_decode(mem, woff[i], n, 0, RUNS, scratch, rb);
        m = r[0];
        if (woff[i] + r[1] > end) return -1 - i;
      }
      const w0 = wofs[i];
      if (m !== wofs[i + 1] - w0) { bad++; continue; }
      for (let k = 0; k < m; k++) if (scratch[k] !== want[w0 + k]) { bad++; break; }
    }
    return bad;
  }

  // ---------------------------------------------------------------- clustering: cheapest table per context
  function cost_argmin_bb(indptr, cols, vals, LT, K, hint, newt, cur, bj, acc) {
    for (let r = 0; r < indptr.length - 1; r++) {
      const j0 = indptr[r], m = indptr[r + 1] - j0;
      for (let j = 0; j < m; j++) bj[j] = cols[j0 + j] * K;
      const p = m < 2 ? m : 2;
      for (let t = 0; t < K; t++) acc[t] = 0;
      for (let j = 0; j < p; j++) {
        const b = bj[j], v = vals[j0 + j];
        for (let t = 0; t < K; t++) acc[t] += v * LT[b + t];
      }
      let bt = hint[r], bc = acc[bt];
      for (let j = p; j < m; j++) bc += vals[j0 + j] * LT[bj[j] + bt];
      for (let t = 0; t < K; t++) {
        if (t === bt) continue;
        let s = acc[t], j = p;
        if (t < bt) {
          if (s > bc) continue;
          while (j < m) { s += vals[j0 + j] * LT[bj[j] + t]; if (s > bc) break; j++; }
          if (s <= bc) { bt = t; bc = s; }
        } else {
          if (s >= bc) continue;
          while (j < m) { s += vals[j0 + j] * LT[bj[j] + t]; if (s >= bc) break; j++; }
          if (s < bc) { bt = t; bc = s; }
        }
      }
      newt[r] = bt; cur[r] = bc;
    }
    return 0;
  }

  const K = { dsp_rle_all, dsm_emit, dsm_verify, dsh_emit, dsh_verify, cost_argmin_bb, rle_n, rle_written, dsm_ref_decode, dsh_ref_decode };

  /* The kernels as Pyodide calls them (as XVK.forPyodide in kernels.js): a numpy array argument arrives as a
   * PyProxy; getBuffer() gives a typed-array view of its memory (no copy), released after the call. */
  K.forPyodide = () => {
    const out = {};
    for (const name of Object.keys(K)) {
      if (name === "forPyodide") continue;
      out[name] = (...args) => {
        const bufs = [];
        try {
          const a = args.map((x) => {
            if (x && typeof x.getBuffer === "function") {
              const b = x.getBuffer(); bufs.push(b);
              if (b.data instanceof BigInt64Array || b.data instanceof BigUint64Array) throw new Error(name + ": 64-bit array passed to a kernel");
              return b.data;
            }
            return x;
          });
          return K[name](...a);
        } finally { for (const b of bufs) b.release(); }
      };
    }
    return out;
  };
  return K;
})();
if (typeof module !== "undefined") module.exports = MSK;
