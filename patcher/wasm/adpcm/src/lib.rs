//! PS1 SPU ADPCM search encoder for the web patcher: the twin of patcher/src/kernels.js snd_encode (and of
//! tools/snd/adpcm.py _encode_core), byte for byte.  Built to WebAssembly (patcher/wasm/build.sh); the page's
//! encoder sub-workers call it instead of the JavaScript loop when it loads.
#![no_std]

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { core::arch::wasm32::unreachable() }

const SF0: [i32; 5] = [0, 60, 115, 98, 122];
const SF1: [i32; 5] = [0, 0, -52, -55, -60];
const LIMIT53: f64 = 9007199254740991.0;

const MAXS: usize = 1 << 20;                  // samples per job (MvC / XvSF samples are far smaller)
const MAXB: usize = MAXS / 28 + 1;
const KMAX: usize = 16;
const MMAX: usize = 65;
const BMAX: usize = 64;
const RMAX: usize = 15;
const NCMAX: usize = BMAX * (2 * RMAX + 1);
const PMAX: usize = KMAX * MMAX * KMAX;

static mut X: [i32; MAXS] = [0; MAXS];
static mut OUT: [u8; MAXB * 16] = [0; MAXB * 16];
static mut BT_PAR: [i32; MAXB * KMAX] = [0; MAXB * KMAX];
static mut BT_COMBO: [i32; MAXB * KMAX] = [0; MAXB * KMAX];
static mut BT_NIB: [i8; MAXB * KMAX * 28] = [0; MAXB * KMAX * 28];

#[no_mangle]
pub extern "C" fn x_ptr() -> *mut i32 { unsafe { core::ptr::addr_of_mut!(X) as *mut i32 } }
#[no_mangle]
pub extern "C" fn out_ptr() -> *mut u8 { unsafe { core::ptr::addr_of_mut!(OUT) as *mut u8 } }
#[no_mangle]
pub extern "C" fn max_samples() -> i32 { MAXS as i32 }

#[inline(always)]
fn clamp16(s: i32) -> i32 { if s > 32767 { 32767 } else if s < -32768 { -32768 } else { s } }

/// greedy error of one (filter, shift); stops as soon as the sum reaches `bound` (the caller only needs to know it is
/// not below it: the sum never decreases)
#[inline(always)]
fn greedy_err(x: &[i32], o: usize, mut s1: i32, mut s2: i32, f0: i32, f1: i32, sh: i32, bound: f64) -> f64 {
    let qs = 12 - sh;
    let step = 1i32 << qs;
    let half = step >> 1;
    let mut err = 0.0f64;
    for i in 0..28 {
        let xi = x[o + i];
        let pred = (s1 * f0 + s2 * f1 + 32) >> 6;
        let mut n = (xi - pred + half) >> qs;
        if n > 7 { n = 7 } else if n < -8 { n = -8 }
        let s = clamp16(n * step + pred);
        let e = (xi - s) as f64;
        err += e * e;
        if err >= bound { return err; }
        s2 = s1;
        s1 = s;
    }
    err
}

struct W {
    cs1: [i32; BMAX], cs2: [i32; BMAX], cerr: [f64; BMAX],
    ns1: [i32; NCMAX], ns2: [i32; NCMAX], nerr: [f64; NCMAX], cpar: [i32; NCMAX], cnib: [i32; NCMAX],
    bpar: [i32; 28 * BMAX], bnib: [i32; 28 * BMAX],
    fin_s1: [i32; KMAX], fin_s2: [i32; KMAX], fin_err: [f64; KMAX], fin_nib: [i32; KMAX * 28],
}
static mut WS: W = W {
    cs1: [0; BMAX], cs2: [0; BMAX], cerr: [0.0; BMAX], ns1: [0; NCMAX], ns2: [0; NCMAX], nerr: [0.0; NCMAX],
    cpar: [0; NCMAX], cnib: [0; NCMAX], bpar: [0; 28 * BMAX], bnib: [0; 28 * BMAX], fin_s1: [0; KMAX], fin_s2: [0; KMAX],
    fin_err: [0.0; KMAX], fin_nib: [0; KMAX * 28],
};

/// the in-block beam: kept list sorted by cost (ties in generation order), one entry per distinct (s1, s2); the same
/// list as sorting every candidate and dropping the later duplicates (kernels.js)
#[allow(clippy::too_many_arguments)]
fn beam_block(x: &[i32], o: usize, s1: i32, s2: i32, f0: i32, f1: i32, sh: i32, bb: usize, r: i32, keep: usize, w: &mut W) -> usize {
    let qs = 12 - sh;
    let step = 1i32 << qs;
    let half = step >> 1;
    let mut nb = 1usize;
    w.cs1[0] = s1;
    w.cs2[0] = s2;
    w.cerr[0] = 0.0;
    for i in 0..28 {
        let xi = x[o + i];
        let mut k = 0usize;
        for b in 0..nb {
            let p1 = w.cs1[b];
            let pred = (p1 * f0 + w.cs2[b] * f1 + 32) >> 6;
            let mut n0 = (xi - pred + half) >> qs;
            if n0 > 7 { n0 = 7 } else if n0 < -8 { n0 = -8 }
            let mut lo = n0 - r;
            let mut hi = n0 + r;
            if lo < -8 { lo = -8 }
            if hi > 7 { hi = 7 }
            let base = w.cerr[b];
            let mut n = lo;
            while n <= hi {
                let s = clamp16(n * step + pred);
                let e = (xi - s) as f64;
                let c = base + e * e;
                n += 1;
                if k == bb && c >= w.nerr[bb - 1] { continue; }
                let mut d = usize::MAX;
                for q in 0..k { if w.ns1[q] == s && w.ns2[q] == p1 { d = q; break; } }
                if d != usize::MAX {
                    if w.nerr[d] <= c { continue; }
                    for q in d..k - 1 {
                        w.ns1[q] = w.ns1[q + 1]; w.ns2[q] = w.ns2[q + 1]; w.nerr[q] = w.nerr[q + 1];
                        w.cpar[q] = w.cpar[q + 1]; w.cnib[q] = w.cnib[q + 1];
                    }
                    k -= 1;
                }
                if k == bb { k -= 1; }
                let mut j = k;
                while j > 0 && w.nerr[j - 1] > c {
                    w.ns1[j] = w.ns1[j - 1]; w.ns2[j] = w.ns2[j - 1]; w.nerr[j] = w.nerr[j - 1];
                    w.cpar[j] = w.cpar[j - 1]; w.cnib[j] = w.cnib[j - 1];
                    j -= 1;
                }
                w.ns1[j] = s; w.ns2[j] = p1; w.nerr[j] = c; w.cpar[j] = b as i32; w.cnib[j] = n - 1;
                k += 1;
            }
        }
        for q in 0..k {
            w.bpar[i * bb + q] = w.cpar[q]; w.bnib[i * bb + q] = w.cnib[q];
            w.cs1[q] = w.ns1[q]; w.cs2[q] = w.ns2[q]; w.cerr[q] = w.nerr[q];
        }
        nb = k;
    }
    let nf = if nb < keep { nb } else { keep };
    for q in 0..nf {
        w.fin_s1[q] = w.cs1[q]; w.fin_s2[q] = w.cs2[q]; w.fin_err[q] = w.cerr[q];
        let mut p = q;
        let mut i = 28;
        while i > 0 {
            i -= 1;
            w.fin_nib[q * 28 + i] = w.bnib[i * bb + p];
            p = w.bpar[i * bb + p] as usize;
        }
    }
    nf
}

static mut PCOST: [f64; PMAX] = [0.0; PMAX];
static mut PS1: [i32; PMAX] = [0; PMAX];
static mut PS2: [i32; PMAX] = [0; PMAX];
static mut PPAR: [i32; PMAX] = [0; PMAX];
static mut PCOMBO: [i32; PMAX] = [0; PMAX];
static mut PNIB: [i32; PMAX * 28] = [0; PMAX * 28];

/// samples in X[0..n] (n >= 28 * nblk), the blocks into OUT; 0 = ok, -1 = settings out of range, -2 = error sum
/// beyond 2**53 (as kernels.js)
#[no_mangle]
pub extern "C" fn encode(n: i32, nblk: i32, s1: i32, s2: i32, kk: i32, mm: i32, bb: i32, r: i32) -> i32 {
    if kk < 1 || kk as usize > KMAX || mm < 1 || mm as usize > MMAX || bb < 1 || bb as usize > BMAX || r < 0 || r as usize > RMAX
        || nblk < 0 || nblk as usize >= MAXB || (n as usize) < nblk as usize * 28 || n as usize > MAXS { return -1; }
    let (kk, mm, bb, nblk) = (kk as usize, mm as usize, bb as usize, nblk as usize);
    unsafe {
        let x: &[i32] = &*core::ptr::addr_of!(X);
        let out: &mut [u8] = &mut *core::ptr::addr_of_mut!(OUT);
        let w: &mut W = &mut *core::ptr::addr_of_mut!(WS);
        let pcost = &mut *core::ptr::addr_of_mut!(PCOST);
        let ps1 = &mut *core::ptr::addr_of_mut!(PS1);
        let ps2 = &mut *core::ptr::addr_of_mut!(PS2);
        let ppar = &mut *core::ptr::addr_of_mut!(PPAR);
        let pcombo = &mut *core::ptr::addr_of_mut!(PCOMBO);
        let pnib = &mut *core::ptr::addr_of_mut!(PNIB);
        let bt_par = &mut *core::ptr::addr_of_mut!(BT_PAR);
        let bt_combo = &mut *core::ptr::addr_of_mut!(BT_COMBO);
        let bt_nib = &mut *core::ptr::addr_of_mut!(BT_NIB);
        let mut ks1 = [0i32; KMAX];
        let mut ks2 = [0i32; KMAX];
        let mut kerr = [0.0f64; KMAX];
        let mut cerr_c = [0.0f64; MMAX];
        let mut cidx_c = [0i32; MMAX];
        let mut porder = [0usize; KMAX];
        let mut nk = 1usize;
        ks1[0] = s1;
        ks2[0] = s2;
        for blk in 0..nblk {
            let o = blk * 28;
            let mut npool = 0usize;
            for p in 0..nk {
                let mut nm = 0usize;                      // all 65 (filter, shift) pairs by greedy error, the best M
                for combo in 0..65i32 {
                    let f = (combo / 13) as usize;
                    let sh = combo - (f as i32) * 13;
                    let e = greedy_err(x, o, ks1[p], ks2[p], SF0[f], SF1[f], sh, if nm < mm { f64::INFINITY } else { cerr_c[mm - 1] });
                    let mut j;
                    if nm < mm { j = nm; nm += 1; } else if e < cerr_c[mm - 1] { j = mm - 1; } else { continue; }
                    while j > 0 && cerr_c[j - 1] > e { cerr_c[j] = cerr_c[j - 1]; cidx_c[j] = cidx_c[j - 1]; j -= 1; }
                    cerr_c[j] = e;
                    cidx_c[j] = combo;
                }
                for m in 0..nm {
                    let combo = cidx_c[m];
                    let f = (combo / 13) as usize;
                    let sh = combo - (f as i32) * 13;
                    let nf = beam_block(x, o, ks1[p], ks2[p], SF0[f], SF1[f], sh, bb, r, kk, w);
                    for q in 0..nf {
                        pcost[npool] = kerr[p] + w.fin_err[q];
                        ps1[npool] = w.fin_s1[q]; ps2[npool] = w.fin_s2[q]; ppar[npool] = p as i32; pcombo[npool] = combo;
                        for i in 0..28 { pnib[npool * 28 + i] = w.fin_nib[q * 28 + i]; }
                        npool += 1;
                    }
                }
            }
            let mut k = 0usize;                           // the best K distinct states of the pool
            for c in 0..npool {
                let v = pcost[c];
                let a1 = ps1[c];
                let a2 = ps2[c];
                if k == kk && v >= pcost[porder[kk - 1]] { continue; }
                let mut d = usize::MAX;
                for q in 0..k { let u = porder[q]; if ps1[u] == a1 && ps2[u] == a2 { d = q; break; } }
                if d != usize::MAX {
                    if pcost[porder[d]] <= v { continue; }
                    for q in d..k - 1 { porder[q] = porder[q + 1]; }
                    k -= 1;
                }
                if k == kk { k -= 1; }
                let mut j = k;
                while j > 0 && pcost[porder[j - 1]] > v { porder[j] = porder[j - 1]; j -= 1; }
                porder[j] = c;
                k += 1;
            }
            for q in 0..k {
                let c = porder[q];
                bt_par[blk * kk + q] = ppar[c];
                bt_combo[blk * kk + q] = pcombo[c];
                for i in 0..28 { bt_nib[(blk * kk + q) * 28 + i] = pnib[c * 28 + i] as i8; }
                ks1[q] = ps1[c]; ks2[q] = ps2[c]; kerr[q] = pcost[c];
                if pcost[c] > LIMIT53 { return -2; }
            }
            nk = k;
        }
        let mut p = 0usize;                               // backtrack from the best final state (slot 0)
        let mut blk = nblk;
        while blk > 0 {
            blk -= 1;
            let combo = bt_combo[blk * kk + p];
            let f = combo / 13;
            let sh = combo - f * 13;
            let ob = blk * 16;
            out[ob] = ((f << 4) | sh) as u8;
            out[ob + 1] = 0;
            let nb = (blk * kk + p) * 28;
            for j in 0..14 {
                out[ob + 2 + j] = ((bt_nib[nb + 2 * j] as i32 & 15) | ((bt_nib[nb + 2 * j + 1] as i32 & 15) << 4)) as u8;
            }
            p = bt_par[blk * kk + p] as usize;
        }
    }
    0
}
