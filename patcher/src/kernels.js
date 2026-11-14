/* Hot loops of the sprite encoders - the JavaScript twin of builder/xvb/kernels.py.
 *
 * Pyodide has no numba, so the browser build runs these instead of the compiled Python kernels.
 * Every function here mirrors the Python function of the same name line by line (same arguments,
 * same flat typed arrays, same integer arithmetic); the patcher's output hash is compared with the
 * command-line build, which is what keeps the two in step.  All values fit 32 bits.
 *
 * Arrays arrive as typed-array VIEWS of the numpy arrays (no copies): Int32Array for int32,
 * Uint8Array for uint8, Float64Array for float64.
 */
"use strict";
const XVK = (() => {

  // ---------------------------------------------------------------- game RLE (decoder 0x8001b5b0)
  function rle_decode(mem, pos, n, out, o) {
    let p = pos, k = 0;
    while (k < n) {
      const b = mem[p++];
      if (b & 0xF0) {                                   // run: (hi+1) bytes of value lo*0x11
        const v = (b & 15) * 0x11, c = (b >> 4) + 1;
        for (let j = 0; j < c; j++) { if (k < n) out[o + k] = v; k++; }
      } else {                                          // literal: (lo+1) raw bytes
        const c = (b & 15) + 1;
        for (let j = 0; j < c; j++) { if (k < n) out[o + k] = mem[p + j]; k++; }
        p += c;
      }
    }
    return p - pos;
  }

  function rle_decode_all(mem, base, toff, tn, out, ooff, clen) {
    for (let i = 0; i < toff.length; i++) clen[i] = rle_decode(mem, base + toff[i], tn[i], out, ooff[i]);
    return 0;
  }

  // ---------------------------------------------------------------- XVM1 (byte symbols)
  function xvm_parse_acc(S, offs, Ws, tab, ctx, lens, NS, RUNS, pen, choice, hist) {
    const NRr = RUNS.length, ESC = 256 + 2 * NRr;
    let cap = 0;
    for (let ti = 0; ti < Ws.length; ti++) cap = Math.max(cap, offs[ti + 1] - offs[ti]);
    const up = new Int32Array(cap + 1), rep = new Int32Array(cap + 1), eq = new Int32Array(cap + 1), cost = new Int32Array(cap + 1);
    for (let ti = 0; ti < Ws.length; ti++) {
      const b = offs[ti], n = offs[ti + 1] - b, W = Ws[ti];
      up[n] = 0; eq[n] = 0; cost[n] = 0;
      for (let i = n - 1; i >= 0; i--) {
        const s = S[b + i];
        const u = i >= W ? S[b + i - W] : 255;
        if (s === u) up[i] = (i !== W - 1) ? up[i + 1] + 1 : 1; else up[i] = 0;
        eq[i] = (i + 1 < n && S[b + i + 1] === s && i !== W - 1) ? eq[i + 1] + 1 : 1;
      }
      for (let i = 0; i < n; i++) {
        const pv = i ? S[b + i - 1] : 255;
        rep[i] = S[b + i] === pv ? eq[i] : 0;
      }
      for (let i = n - 1; i >= 0; i--) {
        const t = tab[b + i] * NS;
        let l = lens[t + S[b + i]];
        if (l === 0) l = lens[t + ESC] + 8;
        let best = cost[i + 1] + 4 * l, bc = 0;
        let lim = up[i];
        for (let r = 0; r < NRr; r++) {
          if (RUNS[r] > lim) break;
          l = lens[t + 256 + r];
          if (l === 0) continue;
          const c = cost[i + RUNS[r]] + 4 * l + pen;
          if (c < best) { best = c; bc = 1 + r; }
        }
        lim = rep[i];
        for (let r = 0; r < NRr; r++) {
          if (RUNS[r] > lim) break;
          l = lens[t + 256 + NRr + r];
          if (l === 0) continue;
          const c = cost[i + RUNS[r]] + 4 * l + pen;
          if (c < best) { best = c; bc = 1 + NRr + r; }
        }
        cost[i] = best; choice[b + i] = bc;
      }
      let i = 0;
      while (i < n) {
        const c = choice[b + i];
        if (c === 0) { hist[ctx[b + i] * NS + S[b + i]]++; i++; }
        else { hist[ctx[b + i] * NS + 255 + c]++; i += RUNS[(c - 1) % NRr]; }
      }
    }
    return 0;
  }

  function xvm_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, out, ooffs) {
    const NRr = RUNS.length, ESC = 256 + 2 * NRr;
    let p = 0;
    for (let ti = 0; ti < Ws.length; ti++) {
      const b = offs[ti], n = offs[ti + 1] - b, W = Ws[ti];
      ooffs[ti] = p;
      let acc = (W >> 3) - 1, nb = 4, i = 0;
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

  function xvm_ref_decode(mem, src, n, model, out) {
    const fbo = model + (mem[model + 8] | (mem[model + 9] << 8));
    let buf = ((mem[src] << 24) | (mem[src + 1] << 16) | (mem[src + 2] << 8) | mem[src + 3]) >>> 0;
    const src0 = src; src += 4;
    const W = ((buf >>> 28) + 1) << 3;
    buf = (buf << 4) >>> 0;
    let c = 12, P = 255, ph = 15 << 8, o = 0;
    while (o < n) {
      const U = o >= W ? out[o - W] : 255;
      const t = mem[model + 76 + (ph | U)];
      let a = model + 4172 + (t << 7) + ((buf >>> 25) & 0x7e);
      let e = mem[a] | (mem[a + 1] << 8);
      if ((e & 0xC000) === 0xC000) {                    // code longer than 6 bits
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
        if (e & 0x1000) {                               // escape: 8 raw bits
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

  function xvm_verify(mem, o2, o3, xvm_end, woff, tn, raw, roff, scratch) {
    let bad = 0;
    for (let i = 0; i < woff.length; i++) {
      const n = tn[i];
      let used;
      if (woff[i] >= xvm_end) {
        used = rle_decode(mem, o2 + woff[i], n, scratch, 0);
        if (o2 + woff[i] + used > o3) return -1 - i;
      } else {
        used = xvm_ref_decode(mem, o2 + woff[i], n, o2, scratch);
        if (woff[i] + used > xvm_end) return -1 - i;
      }
      const r = roff[i];
      for (let k = 0; k < n; k++) if (scratch[k] !== raw[r + k]) { bad++; break; }
    }
    return bad;
  }

  // ---------------------------------------------------------------- XVH1 (pixel symbols)
  function xvh_parse_acc(S, offs, Ws, tab, cq, lens, NS, RUNS, choice, hist) {
    const NRr = RUNS.length;
    let cap = 0;
    for (let ti = 0; ti < Ws.length; ti++) cap = Math.max(cap, offs[ti + 1] - offs[ti]);
    const runlen = new Int32Array(cap + 1), cost = new Int32Array(cap + 1);
    for (let ti = 0; ti < Ws.length; ti++) {
      const b = offs[ti], n = offs[ti + 1] - b, W = Ws[ti];
      runlen[n] = 0; cost[n] = 0;
      for (let i = n - 1; i >= 0; i--) {
        const u = i >= W ? S[b + i - W] : 15;
        runlen[i] = S[b + i] === u ? runlen[i + 1] + 1 : 0;
      }
      for (let i = n - 1; i >= 0; i--) {
        const t = tab[b + i] * NS;
        let l = lens[t + S[b + i]];
        if (l === 0) l = 30;
        let best = cost[i + 1] + l, bc = 0;
        const rl = runlen[i];
        for (let r = 0; r < NRr; r++) {
          if (RUNS[r] > rl) break;
          l = lens[t + 16 + r];
          if (l === 0) l = 30;
          const c = cost[i + RUNS[r]] + l;
          if (c < best) { best = c; bc = r + 1; }
        }
        cost[i] = best; choice[b + i] = bc;
      }
      let i = 0;
      while (i < n) {
        const c = choice[b + i];
        if (c === 0) { hist[cq[b + i] * NS + S[b + i]]++; i++; }
        else { hist[cq[b + i] * NS + 15 + c]++; i += RUNS[c - 1]; }
      }
    }
    return 0;
  }

  function xvh_emit(S, offs, Ws, tab, choice, RUNS, lens, NS, codes, out, ooffs) {
    let p = 0;
    for (let ti = 0; ti < Ws.length; ti++) {
      const b = offs[ti], n = offs[ti + 1] - b, W = Ws[ti];
      ooffs[ti] = p;
      let acc = (W >> 4) - 1, nb = 4, i = 0;
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
      if (nb) out[p++] = (acc << (8 - nb)) & 255;
    }
    return p;
  }

  function xvh_ref_decode(mem, src, n, model, RUNS, out, rb) {
    for (let i = 0; i < 258; i++) rb[i] = 15;
    const src0 = src;
    const map2 = model + mem[model + 8] + (mem[model + 9] << 8);
    const tofs = model + mem[model + 10] + (mem[model + 11] << 8);
    let buf = ((mem[src] << 24) | 0x800000) >>> 0; src++;
    const W = ((buf >>> 28) + 1) * 16;
    buf = (buf << 4) >>> 0;
    let x = 0, L = 15 << 8, UL = 15, lo = 0, o = 0, run = 0;
    while (o < n) {
      const U = rb[x];
      let p;
      if (run === 0) {
        const c1 = mem[model + 12 + (L | (U << 4) | UL)];
        const t = mem[map2 + ((c1 << 4) | rb[x + 1])];
        let rec = model + (mem[tofs + 2 * t] | (mem[tofs + 2 * t + 1] << 8));
        let sp = rec + 12, d = 0;
        for (;;) {
          let tt = (buf << 1) >>> 0;
          if (tt === 0) {
            buf = ((mem[src] << 24) | 0x800000) >>> 0; src++;
            tt = (buf << 1) >>> 0;
          }
          d = d * 2 + (buf >>> 31);
          buf = tt;
          const c = mem[rec++];
          if (d < c) break;
          d -= c; sp += c;
        }
        const sym = mem[sp + d];
        if (sym < 16) p = sym;
        else { run = RUNS[sym - 16] - 1; p = U; }
      } else { run--; p = U; }
      rb[x] = p;
      if (x & 1) out[o++] = lo | (p << 4); else lo = p;
      x++;
      if (x === W) { x = 0; L = 15 << 8; UL = 15; }
      else { L = p << 8; UL = U; }
    }
    return src - src0;
  }

  function xvh_verify(mem, o2, o3, woff, tn, raw, roff, RUNS, scratch, rb) {
    let bad = 0;
    for (let i = 0; i < woff.length; i++) {
      const n = tn[i];
      const used = xvh_ref_decode(mem, o2 + woff[i], n, o2, RUNS, scratch, rb);
      if (o2 + woff[i] + used > o3) return -1 - i;
      const r = roff[i];
      for (let k = 0; k < n; k++) if (scratch[k] !== raw[r + k]) { bad++; break; }
    }
    return bad;
  }

  // ---------------------------------------------------------------- Huffman code lengths
  function hufflens_many(counts, NS, K, limit, lens, work) {
    const C = 0, PAR = 2 * NS, AL = 4 * NS, ORD = 6 * NS;
    const less = (x, y) => work[C + x] < work[C + y] || (work[C + x] === work[C + y] && x < y);
    for (let k = 0; k < K; k++) {
      const base = k * NS;
      let m = 0;
      for (let s = 0; s < NS; s++) {
        lens[base + s] = 0;
        if (counts[base + s] !== 0) { work[C + s] = counts[base + s]; work[AL + m] = s; m++; }
      }
      if (m === 0) continue;
      if (m === 1) { lens[base + work[AL]] = 1; continue; }
      const nidx = m;
      for (let j = 0; j < m; j++) work[ORD + j] = work[AL + j];        // the used symbols, ascending
      // binary min-heap of node ids in work[AL..], ordered by (count, id)
      for (let j = (m >> 1) - 1; j >= 0; j--) {
        let q = j;
        for (;;) {
          let c1 = 2 * q + 1;
          if (c1 >= m) break;
          const c2 = c1 + 1;
          let x = work[AL + c1];
          if (c2 < m) { const y = work[AL + c2]; if (less(y, x)) { c1 = c2; x = y; } }
          const y = work[AL + q];
          if (less(x, y)) { work[AL + q] = x; work[AL + c1] = y; q = c1; } else break;
        }
      }
      let uid = NS, alive = m;
      while (alive > 1) {
        let a = 0, b = 0;
        for (let rep = 0; rep < 2; rep++) {                            // pop the two smallest
          const top = work[AL];
          alive--;
          const last = work[AL + alive];
          let q = 0;
          for (;;) {                                                   // sift `last` down from the root
            let c1 = 2 * q + 1;
            if (c1 >= alive) break;
            const c2 = c1 + 1;
            let x = work[AL + c1];
            if (c2 < alive) { const y = work[AL + c2]; if (less(y, x)) { c1 = c2; x = y; } }
            if (less(x, last)) { work[AL + q] = x; q = c1; } else break;
          }
          if (alive > 0) work[AL + q] = last;
          if (rep === 0) a = top; else b = top;
        }
        work[C + uid] = work[C + a] + work[C + b];
        work[PAR + a] = uid; work[PAR + b] = uid;
        let q = alive; alive++;                                        // push the new node, sift up
        while (q > 0) {
          const par = (q - 1) >> 1;
          const y = work[AL + par];
          if (less(uid, y)) { work[AL + q] = y; q = par; } else break;
        }
        work[AL + q] = uid;
        uid++;
      }
      const root = uid - 1;
      let mx = 0;
      for (let j = 0; j < nidx; j++) {
        const s = work[ORD + j];
        let d = 0, x = s;
        while (x !== root) { x = work[PAR + x]; d++; }
        lens[base + s] = d;
        if (d > mx) mx = d;
      }
      if (mx > limit) {
        let Kr = 0;
        for (let j = 0; j < nidx; j++) {
          const s = work[ORD + j];
          if (lens[base + s] > limit) lens[base + s] = limit;
          Kr += 1 << (limit - lens[base + s]);
        }
        const full = 1 << limit;
        while (Kr > full) {
          // symbols by (longest code first, rarest first), stable in symbol order
          let done = false;
          for (let j = 0; j < nidx; j++) work[AL + j] = work[ORD + j];
          for (let j = 1; j < nidx; j++) {                             // insertion sort, stable
            const x = work[AL + j];
            let q = j - 1;
            while (q >= 0) {
              const y = work[AL + q];
              if (lens[base + y] < lens[base + x] || (lens[base + y] === lens[base + x] && counts[base + y] > counts[base + x])) { work[AL + q + 1] = y; q--; }
              else break;
            }
            work[AL + q + 1] = x;
          }
          for (let j = 0; j < nidx; j++) {
            const s = work[AL + j];
            if (lens[base + s] < limit) {
              Kr -= 1 << (limit - lens[base + s] - 1); lens[base + s]++;
              if (Kr <= full) { done = true; break; }
            }
          }
          if (done) break;
        }
        // use the slack, most frequent symbols first (stable in symbol order)
        for (let j = 0; j < nidx; j++) work[AL + j] = work[ORD + j];
        for (let j = 1; j < nidx; j++) {
          const x = work[AL + j];
          let q = j - 1;
          while (q >= 0) {
            const y = work[AL + q];
            if (counts[base + y] < counts[base + x]) { work[AL + q + 1] = y; q--; } else break;
          }
          work[AL + q + 1] = x;
        }
        for (let j = 0; j < nidx; j++) {
          const s = work[AL + j];
          while (lens[base + s] > 1 && Kr + (1 << (limit - lens[base + s])) <= full) { Kr += 1 << (limit - lens[base + s]); lens[base + s]--; }
        }
      }
    }
    return 0;
  }

  // ---------------------------------------------------------------- argsort with numpy's tie order
  function argsort_np(v, idx, stack) {
    const num = v.length;
    for (let i = 0; i < num; i++) idx[i] = i;
    if (num < 2) return 0;
    let pl = 0, pr = num - 1, sp = 0, cdepth = 0, t = num, tmp;
    while (t > 1) { t >>= 1; cdepth++; }
    cdepth *= 2;
    for (;;) {
      if (cdepth < 0) {                                  // heapsort of idx[pl..pr]
        let n = pr - pl + 1;
        const a = pl - 1;
        for (let l = n >> 1; l > 0; l--) {
          tmp = idx[a + l];
          let i = l, j = l << 1;
          while (j <= n) {
            if (j < n && v[idx[a + j]] < v[idx[a + j + 1]]) j++;
            if (v[tmp] < v[idx[a + j]]) { idx[a + i] = idx[a + j]; i = j; j += j; } else break;
          }
          idx[a + i] = tmp;
        }
        while (n > 1) {
          tmp = idx[a + n]; idx[a + n] = idx[a + 1]; n--;
          let i = 1, j = 2;
          while (j <= n) {
            if (j < n && v[idx[a + j]] < v[idx[a + j + 1]]) j++;
            if (v[tmp] < v[idx[a + j]]) { idx[a + i] = idx[a + j]; i = j; j += j; } else break;
          }
          idx[a + i] = tmp;
        }
      } else {
        while (pr - pl > 15) {
          const pm = pl + ((pr - pl) >> 1);
          if (v[idx[pm]] < v[idx[pl]]) { tmp = idx[pm]; idx[pm] = idx[pl]; idx[pl] = tmp; }
          if (v[idx[pr]] < v[idx[pm]]) { tmp = idx[pr]; idx[pr] = idx[pm]; idx[pm] = tmp; }
          if (v[idx[pm]] < v[idx[pl]]) { tmp = idx[pm]; idx[pm] = idx[pl]; idx[pl] = tmp; }
          const vp = v[idx[pm]];
          let pi = pl, pj = pr - 1;
          tmp = idx[pm]; idx[pm] = idx[pj]; idx[pj] = tmp;
          for (;;) {
            pi++; while (v[idx[pi]] < vp) pi++;
            pj--; while (vp < v[idx[pj]]) pj--;
            if (pi >= pj) break;
            tmp = idx[pi]; idx[pi] = idx[pj]; idx[pj] = tmp;
          }
          const pk = pr - 1;
          tmp = idx[pi]; idx[pi] = idx[pk]; idx[pk] = tmp;
          cdepth--;
          if (pi - pl < pr - pi) {                       // the larger partition waits on the stack
            stack[sp] = pi + 1; stack[sp + 1] = pr; stack[sp + 2] = cdepth; sp += 3;
            pr = pi - 1;
          } else {
            stack[sp] = pl; stack[sp + 1] = pi - 1; stack[sp + 2] = cdepth; sp += 3;
            pl = pi + 1;
          }
        }
        for (let pi = pl + 1; pi <= pr; pi++) {          // insertion sort
          const vi = idx[pi], vp = v[vi];
          let pj = pi;
          while (pj > pl && vp < v[idx[pj - 1]]) { idx[pj] = idx[pj - 1]; pj--; }
          idx[pj] = vi;
        }
      }
      if (sp === 0) break;
      sp -= 3;
      pl = stack[sp]; pr = stack[sp + 1]; cdepth = stack[sp + 2];
    }
    return 0;
  }

  // ---------------------------------------------------------------- clustering: cheapest table per context
  function cost_argmin(indptr, cols, vals, LT, K, newt, cur, acc) {
    for (let r = 0; r < indptr.length - 1; r++) {
      for (let t = 0; t < K; t++) acc[t] = 0;
      for (let j = indptr[r]; j < indptr[r + 1]; j++) {
        const b = cols[j] * K, v = vals[j];
        for (let t = 0; t < K; t++) acc[t] += v * LT[b + t];
      }
      let best = 0;
      for (let t = 1; t < K; t++) if (acc[t] < acc[best]) best = t;
      newt[r] = best; cur[r] = acc[best];
    }
    return 0;
  }

  // ---------------------------------------------------------------- 1.2 sound: tools/snd/adpcm.py, resample.py
  // Twins of the numba functions _decode_core, _encode_core (with _greedy_err, _beam_block, _pack) and
  // _resample_core.  The Python side (builder/xvb/web.py) hands int32 copies of the int64 arrays.  Values that
  // can pass 2**31 (squared errors and their sums, the resampler's positions and products) are plain Numbers:
  // exact integers below 2**53 (checked where a sum could grow); shifts of such values are floor divisions by
  // powers of two, other divisions exact floor divisions (fdiv).
  const SF0 = [0, 60, 115, 98, 122], SF1 = [0, 0, -52, -55, -60];
  const LIMIT53 = 9007199254740991;

  function fdiv(a, b) {               // floor(a / b), exact for integers |a|, |b| < 2**53, b > 0
    let q = Math.floor(a / b);
    while (q * b > a) q--;
    while ((q + 1) * b <= a) q++;
    return q;
  }

  function snd_decode(b, nblk, s1, s2, out) {
    for (let k = 0; k < nblk; k++) {
      const o = k * 16, hdr = b[o];
      let sh = hdr & 15; if (sh > 12) sh = 9;
      let f = (hdr >> 4) & 7; if (f > 4) f = 4;
      const f0 = SF0[f], f1 = SF1[f];
      for (let i = 0; i < 28; i++) {
        let n = (b[o + 2 + (i >> 1)] >> ((i & 1) * 4)) & 15;
        if (n >= 8) n -= 16;
        let s = ((n << 12) >> sh) + ((s1 * f0 + s2 * f1 + 32) >> 6);
        if (s > 32767) s = 32767; else if (s < -32768) s = -32768;
        s2 = s1; s1 = s;
        out[k * 28 + i] = s;
      }
    }
    return 0;                                           // (the Python caller does not use the final state)
  }

  function greedy_err(x, o, s1, s2, f0, f1, sh) {
    const qs = 12 - sh, step = 1 << qs, half = step >> 1;
    let err = 0;
    for (let i = 0; i < 28; i++) {
      const xi = x[o + i];
      const pred = (s1 * f0 + s2 * f1 + 32) >> 6;
      let n = (xi - pred + half) >> qs;
      if (n > 7) n = 7; else if (n < -8) n = -8;
      let s = n * step + pred;
      if (s > 32767) s = 32767; else if (s < -32768) s = -32768;
      const e = xi - s;
      err += e * e;
      s2 = s1; s1 = s;
    }
    return err;
  }

  function snd_pack(out, o, f, sh, nib, no) {
    out[o] = (f << 4) | sh;
    out[o + 1] = 0;
    for (let j = 0; j < 14; j++) out[o + 2 + j] = (nib[no + 2 * j] & 15) | ((nib[no + 2 * j + 1] & 15) << 4);
  }

  function beam_block(x, o, s1, s2, f0, f1, sh, B, R, keep, W) {
    const qs = 12 - sh, step = 1 << qs, half = step >> 1;
    const { cs1, cs2, cerr, ns1, ns2, nerr, ccost, cs, cpar, cnib, order, bpar, bnib, fin_s1, fin_s2, fin_err, fin_nib } = W;
    let nb = 1;
    cs1[0] = s1; cs2[0] = s2; cerr[0] = 0;
    for (let i = 0; i < 28; i++) {
      const xi = x[o + i];
      let nc = 0;
      for (let b = 0; b < nb; b++) {
        const p1 = cs1[b];
        const pred = (p1 * f0 + cs2[b] * f1 + 32) >> 6;
        let n0 = (xi - pred + half) >> qs;
        if (n0 > 7) n0 = 7; else if (n0 < -8) n0 = -8;
        let lo = n0 - R, hi = n0 + R;
        if (lo < -8) lo = -8;
        if (hi > 7) hi = 7;
        const base = cerr[b];
        for (let n = lo; n <= hi; n++) {
          let s = n * step + pred;
          if (s > 32767) s = 32767; else if (s < -32768) s = -32768;
          const e = xi - s;
          ccost[nc] = base + e * e; cs[nc] = s; cpar[nc] = b; cnib[nc] = n;
          nc++;
        }
      }
      for (let a = 0; a < nc; a++) {                    // stable insertion sort of candidate indices by cost
        const v = ccost[a];
        let j = a - 1;
        while (j >= 0 && ccost[order[j]] > v) { order[j + 1] = order[j]; j--; }
        order[j + 1] = a;
      }
      let k = 0;
      for (let a = 0; a < nc; a++) {                    // the best B with distinct (s1, s2)
        const c = order[a], s = cs[c], p = cs1[cpar[c]];
        let dup = false;
        for (let q = 0; q < k; q++) if (ns1[q] === s && ns2[q] === p) { dup = true; break; }
        if (dup) continue;
        ns1[k] = s; ns2[k] = p; nerr[k] = ccost[c];
        bpar[i * B + k] = cpar[c]; bnib[i * B + k] = cnib[c];
        k++;
        if (k === B) break;
      }
      for (let q = 0; q < k; q++) { cs1[q] = ns1[q]; cs2[q] = ns2[q]; cerr[q] = nerr[q]; }
      nb = k;
    }
    const nf = nb < keep ? nb : keep;
    for (let q = 0; q < nf; q++) {
      fin_s1[q] = cs1[q]; fin_s2[q] = cs2[q]; fin_err[q] = cerr[q];
      let p = q;
      for (let i = 27; i >= 0; i--) { fin_nib[q * 28 + i] = bnib[i * B + p]; p = bpar[i * B + p]; }
    }
    return nf;
  }

  function snd_encode(x, nblk, s1, s2, K, M, B, R, out) {
    const NC = B * (2 * R + 1);
    const W = {
      cs1: new Int32Array(B), cs2: new Int32Array(B), cerr: new Float64Array(B), ns1: new Int32Array(B), ns2: new Int32Array(B),
      nerr: new Float64Array(B), ccost: new Float64Array(NC), cs: new Int32Array(NC), cpar: new Int32Array(NC), cnib: new Int32Array(NC),
      order: new Int32Array(NC), bpar: new Int32Array(28 * B), bnib: new Int32Array(28 * B),
      fin_s1: new Int32Array(K), fin_s2: new Int32Array(K), fin_err: new Float64Array(K), fin_nib: new Int32Array(K * 28),
    };
    const cerr_c = new Float64Array(M), cidx_c = new Int32Array(M);
    const P = K * M * K;
    const pcost = new Float64Array(P), ps1_ = new Int32Array(P), ps2_ = new Int32Array(P), ppar = new Int32Array(P),
      pcombo = new Int32Array(P), pnib = new Int32Array(P * 28), porder = new Int32Array(P);
    const ks1 = new Int32Array(K), ks2 = new Int32Array(K), kerr = new Float64Array(K);
    let nk = 1;
    ks1[0] = s1; ks2[0] = s2;
    const bt_par = new Int32Array(nblk * K), bt_combo = new Int32Array(nblk * K), bt_nib = new Int8Array(nblk * K * 28);
    for (let blk = 0; blk < nblk; blk++) {
      const o = blk * 28;
      let npool = 0;
      for (let p = 0; p < nk; p++) {
        let nm = 0;                                     // all 65 (filter, shift) pairs by greedy error, the best M
        for (let combo = 0; combo < 65; combo++) {
          const f = (combo / 13) | 0, sh = combo - f * 13;
          const e = greedy_err(x, o, ks1[p], ks2[p], SF0[f], SF1[f], sh);
          let j;
          if (nm < M) { j = nm; nm++; }
          else if (e < cerr_c[M - 1]) j = M - 1;
          else continue;
          while (j > 0 && cerr_c[j - 1] > e) { cerr_c[j] = cerr_c[j - 1]; cidx_c[j] = cidx_c[j - 1]; j--; }
          cerr_c[j] = e; cidx_c[j] = combo;
        }
        for (let m = 0; m < nm; m++) {
          const combo = cidx_c[m], f = (combo / 13) | 0, sh = combo - f * 13;
          const nf = beam_block(x, o, ks1[p], ks2[p], SF0[f], SF1[f], sh, B, R, K, W);
          for (let q = 0; q < nf; q++) {
            pcost[npool] = kerr[p] + W.fin_err[q];
            ps1_[npool] = W.fin_s1[q]; ps2_[npool] = W.fin_s2[q]; ppar[npool] = p; pcombo[npool] = combo;
            for (let i = 0; i < 28; i++) pnib[npool * 28 + i] = W.fin_nib[q * 28 + i];
            npool++;
          }
        }
      }
      for (let a = 0; a < npool; a++) {                 // stable sort of the pool by cost, the best K distinct states
        const v = pcost[a];
        let j = a - 1;
        while (j >= 0 && pcost[porder[j]] > v) { porder[j + 1] = porder[j]; j--; }
        porder[j + 1] = a;
      }
      let k = 0;
      for (let a = 0; a < npool; a++) {
        const c = porder[a];
        let dup = false;
        for (let q = 0; q < k; q++) if (ks1[q] === ps1_[c] && ks2[q] === ps2_[c]) { dup = true; break; }
        if (dup) continue;
        bt_par[blk * K + k] = ppar[c]; bt_combo[blk * K + k] = pcombo[c];
        for (let i = 0; i < 28; i++) bt_nib[(blk * K + k) * 28 + i] = pnib[c * 28 + i];
        ks1[k] = ps1_[c]; ks2[k] = ps2_[c]; kerr[k] = pcost[c];
        if (pcost[c] > LIMIT53) throw new Error("snd_encode: error sum beyond 2**53");
        k++;
        if (k === K) break;
      }
      nk = k;
    }
    const nib = new Int32Array(28);
    let p = 0;
    for (let blk = nblk - 1; blk >= 0; blk--) {         // backtrack from the best final state (slot 0)
      const combo = bt_combo[blk * K + p], f = (combo / 13) | 0, sh = combo - f * 13;
      for (let i = 0; i < 28; i++) nib[i] = bt_nib[(blk * K + p) * 28 + i];
      snd_pack(out, blk * 16, f, sh, nib, 0);
      p = bt_par[blk * K + p];
    }
    return 0;
  }

  function snd_resample(x, n, num, den, D, nout, H, NTAB, P, out) {
    const WB = 32768, T32 = 4294967296;               // 2**WBITS, 2**32
    const inv = fdiv(140737488355328, D);              // (1 << (WBITS + 32)) // D
    const dq = fdiv(den, num), dr = den - dq * num;
    const tq = fdiv(num * P, D), tr = num * P - tq * D;
    let ip = 0, fr = 0;
    for (let j = 0; j < nout; j++) {
      let acc = 0, ssum = 0;
      let a = fr * P, i = fdiv(a, D), r = a - i * D, k = ip;
      while (i < NTAB) {                                // taps at and left of t
        const w = Math.floor((r * inv) / T32);
        const h0 = H[i];
        const c = h0 + Math.floor(((H[i + 1] - h0) * w) / WB);
        ssum += c;
        if (k >= 0 && k < n) acc += x[k] * c;
        k--; i += tq; r += tr;
        if (r >= D) { r -= D; i++; }
      }
      a = (num - fr) * P; i = fdiv(a, D); r = a - i * D; k = ip + 1;
      while (i < NTAB) {                                // taps right of t
        const w = Math.floor((r * inv) / T32);
        const h0 = H[i];
        const c = h0 + Math.floor(((H[i + 1] - h0) * w) / WB);
        ssum += c;
        if (k >= 0 && k < n) acc += x[k] * c;
        k++; i += tq; r += tr;
        if (r >= D) { r -= D; i++; }
      }
      if (Math.abs(acc) > LIMIT53 / 4 || ssum <= 0) throw new Error("snd_resample: sum out of range");
      let y = fdiv(2 * acc + ssum, 2 * ssum);
      if (y > 32767) y = 32767; else if (y < -32768) y = -32768;
      out[j] = y;
      ip += dq; fr += dr;
      if (fr >= num) { fr -= num; ip++; }
    }
    return 0;
  }

  const K = { cost_argmin, rle_decode_all, xvm_parse_acc, xvm_emit, xvm_verify, xvh_parse_acc, xvh_emit, xvh_verify, hufflens_many, argsort_np,
              snd_decode, snd_encode, snd_resample };

  /* The kernels as Pyodide calls them: a numpy array argument arrives as a PyProxy; getBuffer() gives a
   * typed-array view of its memory (no copy), which is released after the call.  Nothing in a kernel
   * allocates Python memory, so the views stay valid for the duration of the call. */
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
if (typeof module !== "undefined") module.exports = XVK;
