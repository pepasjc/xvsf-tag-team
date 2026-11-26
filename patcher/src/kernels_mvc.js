/* Hot loops of the MvC DSR1 sprite encoder - the JavaScript twin of games/mvc/tools/codec2/dsr.py tile_decisions /
 * rc_encode (numba on the command line; builder/mvcb/kern.py installs these in the browser).  Line-by-line mirror:
 * same arguments, flat typed arrays.  px: Int32Array H*W (row major), nodes / pairs(flat, 2 per row) / jump / cont / lp:
 * Int32Array, probs: Int32Array flat (stride pstride), outp / outb / out: Int32Array or Float64Array.
 * The range coder's `low` needs 33 bits: plain Numbers (exact below 2^53).
 */
"use strict";
const MVK = (() => {
  function dsr_tile_decisions(px, H, W, nodes, pairs, jump, cont, lp, probs, pstride, outp, outb) {
    let k = 0;
    const f = new Int32Array(8);
    const P = (y, x) => px[y * W + x];
    for (let y = 0; y < H; y++) {
      let inrun = false, pos = 0;
      for (let x = 0; x < W; x++) {
        f[0] = x > 0 ? P(y, x - 1) : 15;
        f[1] = y > 0 ? P(y - 1, x) : 15;
        f[2] = (y > 0 && x > 0) ? P(y - 1, x - 1) : 15;
        f[3] = (y > 0 && x + 1 < W) ? P(y - 1, x + 1) : 15;
        f[4] = x > 1 ? P(y, x - 2) : 15;
        f[5] = y > 1 ? P(y - 2, x) : 15;
        f[6] = (y > 0 && x > 1) ? P(y - 1, x - 2) : 15;
        f[7] = (y > 0 && x + 2 < W) ? P(y - 1, x + 2) : 15;
        const s = P(y, x);
        let known;
        if (inrun) {
          const c = (f[1] === f[2] ? 1 : 0) | (f[3] === f[1] ? 2 : 0) | (f[1] !== 15 ? 4 : 0) | (pos << 3) |
                    (f[7] === f[3] ? 32 : 0) | (f[5] === f[1] ? 64 : 0) |
                    (((y > 1 && x + 1 < W) ? P(y - 2, x + 1) : 15) === f[3] ? 128 : 0);
          if (s === f[1]) { outp[k] = cont[c]; outb[k] = 1; k++; pos = Math.min(pos + 1, 3); continue; }
          outp[k] = cont[c]; outb[k] = 0; k++;
          inrun = false; known = true;
        } else known = false;
        let i = jump[f[0] * 16 + f[1]], nd;
        while (true) {
          nd = nodes[i];
          if (nd & 0x8000) break;
          const t = nd & 0xFF;
          let r;
          if (t < 40) { const n = (t / 5) | 0, kk = t % 5; r = kk < 4 ? ((f[n] >> kk) & 1) : (f[n] === 15 ? 1 : 0); }
          else r = f[pairs[(t - 40) * 2]] === f[pairs[(t - 40) * 2 + 1]] ? 1 : 0;
          i = r ? (nd >> 16) : i + 1;
        }
        const lf = nd & 0x7FFF;
        if (!known) {
          outp[k] = probs[lf * pstride];
          if (s === f[1]) { outb[k] = 1; k++; inrun = true; pos = 0; continue; }
          outb[k] = 0; k++;
        }
        if (f[0] !== f[1]) {
          outp[k] = lp[lf];
          if (s === f[0]) { outb[k] = 1; k++; continue; }
          outb[k] = 0; k++;
        }
        let idx = 1;
        for (const sh of [3, 2, 1, 0]) { const b = (s >> sh) & 1; outp[k] = probs[lf * pstride + idx]; outb[k] = b; k++; idx = idx * 2 + b; }
      }
    }
    return k;
  }

  function dsr_rc_encode(ps, bs, n, out) {
    let low = 0, rng = 0xFFFFFFFF, cache = 0, csize = 1, o = 0;
    const T32 = 4294967296, T24 = 16777216;
    for (let i = 0; i < n + 5; i++) {
      let nsh;
      if (i < n) {
        const bound = Math.floor(rng / 256) * ps[i];
        if (bs[i] === 0) rng = bound; else { low += bound; rng -= bound; }
        nsh = 0;
        while (rng < T24) { rng = (rng * 256) % T32; nsh++; }
      } else nsh = 1;
      for (let q = 0; q < nsh; q++) {
        if (low < 0xFF000000 || low >= T32) {
          const carry = Math.floor(low / T32); let temp = cache;
          while (true) {
            out[o++] = (temp + carry) & 0xFF; temp = 0xFF;
            csize--;
            if (csize === 0) break;
          }
          cache = Math.floor(low / T24) & 0xFF;
        }
        csize++;
        low = (low % T24) * 256;
      }
    }
    return o;
  }

  // exact model of the MIPS decoder (dsr.py ref_decode) -> bytes consumed; mem Uint8Array, out Uint8Array (n bytes)
  function dsr_ref_decode(mem, src, n, nodes, pairs, jump, cont, lp, probs, pstride, out) {
    const T32 = 4294967296, T24 = 16777216;
    const wb = mem[src], W = wb * 2, H = Math.floor((2 * n) / W);
    let p = src + 1, code = 0;
    for (let i = 0; i < 4; i++) code = code * 256 + mem[p++];
    let rng = 0xFFFFFFFF;
    const px = new Int32Array(H * W).fill(15), f = new Int32Array(8);
    const P = (y, x) => px[y * W + x];
    const bit = (prob) => {
      const bound = Math.floor(rng / 256) * prob; let b;
      if (code < bound) { b = 0; rng = bound; } else { b = 1; code -= bound; rng -= bound; }
      while (rng < T24) { rng = (rng * 256) % T32; code = (code * 256 + mem[p++]) % T32; }
      return b;
    };
    for (let y = 0; y < H; y++) {
      let inrun = false, pos = 0;
      for (let x = 0; x < W; x++) {
        f[0] = x > 0 ? P(y, x - 1) : 15;
        f[1] = y > 0 ? P(y - 1, x) : 15;
        f[2] = (y > 0 && x > 0) ? P(y - 1, x - 1) : 15;
        f[3] = (y > 0 && x + 1 < W) ? P(y - 1, x + 1) : 15;
        f[4] = x > 1 ? P(y, x - 2) : 15;
        f[5] = y > 1 ? P(y - 2, x) : 15;
        f[6] = (y > 0 && x > 1) ? P(y - 1, x - 2) : 15;
        f[7] = (y > 0 && x + 2 < W) ? P(y - 1, x + 2) : 15;
        let known = false;
        if (inrun) {
          const c = (f[1] === f[2] ? 1 : 0) | (f[3] === f[1] ? 2 : 0) | (f[1] !== 15 ? 4 : 0) | (pos << 3) |
                    (f[7] === f[3] ? 32 : 0) | (f[5] === f[1] ? 64 : 0) |
                    (((y > 1 && x + 1 < W) ? P(y - 2, x + 1) : 15) === f[3] ? 128 : 0);
          if (bit(cont[c]) === 1) { px[y * W + x] = f[1]; pos = Math.min(pos + 1, 3); continue; }
          inrun = false; known = true;
        }
        let i = jump[f[0] * 16 + f[1]], nd;
        while (true) {
          nd = nodes[i];
          if (nd & 0x8000) break;
          const t = nd & 0xFF; let r;
          if (t < 40) { const nn = (t / 5) | 0, kk = t % 5; r = kk < 4 ? ((f[nn] >> kk) & 1) : (f[nn] === 15 ? 1 : 0); }
          else r = f[pairs[(t - 40) * 2]] === f[pairs[(t - 40) * 2 + 1]] ? 1 : 0;
          i = r ? (nd >> 16) : i + 1;
        }
        const lf = nd & 0x7FFF;
        if (!known) {
          if (bit(probs[lf * pstride]) === 1) { px[y * W + x] = f[1]; inrun = true; pos = 0; continue; }
        }
        if (f[0] !== f[1]) {
          if (bit(lp[lf]) === 1) { px[y * W + x] = f[0]; continue; }
        }
        let idx = 1;
        while (idx < 16) idx = idx * 2 + bit(probs[lf * pstride + idx]);
        px[y * W + x] = idx - 16;
      }
    }
    for (let k = 0; k < n; k++) { const q = 2 * k; out[k] = px[q] | (px[q + 1] << 4); }
    return p - src;
  }

  function dsh_ref_decode_mvc(mem, src, n, model, RUNS, out, rb) {   // MvC width code (common/dsp/dsh.py wm = 1, RAW = 1)
    for (let i = 0; i < 260; i++) rb[i] = 15;
    const src0 = src;
    const m1 = model + 12 + 2 * (mem[model + 10] | (mem[model + 11] << 8));
    let buf = 0, nbits = 0, v = 0, k = 0, wc = 0;
    for (;;) {
      if (nbits === 0) { buf = mem[src++]; nbits = 8; }
      nbits--; v = v * 2 + ((buf >> nbits) & 1); k++;
      if ((k === 1 && v === 0) || (k === 2 && v === 2)) { wc = 3 + 4 * (v >> 1); break; }
      if (k === 8) { wc = v & 63; break; }
    }
    const W = (wc + 1) * 4;
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

  const K = { dsr_tile_decisions, dsr_rc_encode, dsr_ref_decode, dsh_ref_decode_mvc };
  /* as Pyodide calls them (MSK.forPyodide): numpy arguments arrive as PyProxy -> typed-array views */
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
          const r = K[name](...a);
          return Array.isArray(r) ? r.join(",") : r;
        } finally { for (const b of bufs) b.release(); }
      };
    }
    return out;
  };
  return K;
})();
if (typeof module !== "undefined") module.exports = MVK;
