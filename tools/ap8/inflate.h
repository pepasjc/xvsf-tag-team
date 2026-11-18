/* Raw-deflate decoder for the 8 MB loader module (also compiled on the host by tools/ap8/inftest.c).
 *
 * Streaming on the INPUT side: the compressed data is still arriving from the CD while we decode.
 * s->lim is the address up to which input is known to be in memory minus a safety margin; when the
 * read pointer passes it, s->more(s) must block until more has arrived (and move lim), or return 0
 * (read error / timeout).  When everything has arrived, more() sets lim far beyond the data.
 * Tables: one level, indexed by the next `max code length` bits (LSB first), entry = symbol << 4 | length.
 */
typedef unsigned int iu32;
typedef unsigned short iu16;
typedef unsigned char iu8;

struct inf {
    const iu8 *in, *lim;
    iu8 *out, *oend;
    iu8 *cur;                           /* output position, valid inside more(): everything below it is final */
    iu32 bb;
    int bc;
    int (*more)(struct inf *);
    iu16 *lt, *dt;                      /* 32768 entries each */
};
#define INF_MARGIN 40                   /* lim = arrived - INF_MARGIN: one loop pass never consumes more */

static const iu16 inf_lbase[29] = { 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258 };
static const iu8 inf_lext[29] = { 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0 };
static const iu16 inf_dbase[30] = { 1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577 };
static const iu8 inf_dext[30] = { 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13 };
static const iu8 inf_order[19] = { 16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15 };

/* canonical code -> table; returns the index mask (2^max - 1), or -1 for an over-subscribed code */
static int inf_build(iu16 *tab, const iu8 *len, int n)
{
    int count[16], next[16], i, max = 0, code = 0, size;
    for (i = 0; i < 16; i++) count[i] = 0;
    for (i = 0; i < n; i++) count[len[i]]++;
    count[0] = 0;
    for (i = 1; i < 16; i++) {
        code = (code + count[i - 1]) << 1;
        next[i] = code;
        if (count[i]) max = i;
        if (code + count[i] > (1 << i)) return -1;
    }
    if (max == 0) max = 1;
    size = 1 << max;
    for (i = 0; i < size; i++) tab[i] = 0;                      /* length 0 = invalid code */
    for (i = 0; i < n; i++) {
        int l = len[i], c, r, k;
        if (!l) continue;
        c = next[l]++;
        for (r = 0, k = 0; k < l; k++) r |= ((c >> k) & 1) << (l - 1 - k);
        for (; r < size; r += 1 << l) tab[r] = (iu16)(i << 4 | l);
    }
    return size - 1;
}

#define INF_FILL()  while (bc <= 24) { bb |= (iu32)*in++ << bc; bc += 8; }
#define INF_BITS(v, n) { v = bb & ((1u << (n)) - 1); bb >>= (n); bc -= (n); }

/* returns 0 = ok (s->out is the end of the output), else an error number */
#ifdef __GNUC__
__attribute__((optimize("O2")))         /* the module is built for size; this loop decides the load time */
#endif
static int inf_run(struct inf *s)
{
    const iu8 *in = s->in;
    iu8 *out = s->out, *oend = s->oend;
    iu32 bb = 0, v;
    int bc = 0, last, type, lm, dm, i;
    iu8 len[320];
    do {
        if (in >= s->lim) { s->in = in; s->cur = out; if (!s->more(s)) return 1; }
        INF_FILL();
        INF_BITS(last, 1);
        INF_BITS(type, 2);
        if (type == 0) {
            iu32 n;
            INF_BITS(v, bc & 7);
            in -= bc >> 3; bb = 0; bc = 0;                      /* whole bytes back to the input */
            n = in[0] | in[1] << 8;
            if ((n ^ (in[2] | in[3] << 8)) != 0xffff) return 2;
            in += 4;
            if (out + n > oend) return 3;
            while (n) {
                if (in >= s->lim) { s->in = in; s->cur = out; if (!s->more(s)) return 1; }
                *out++ = *in++; n--;
            }
            continue;
        }
        if (type == 3) return 4;
        if (type == 1) {
            for (i = 0; i < 144; i++) len[i] = 8;
            for (; i < 256; i++) len[i] = 9;
            for (; i < 280; i++) len[i] = 7;
            for (; i < 288; i++) len[i] = 8;
            lm = inf_build(s->lt, len, 288);
            for (i = 0; i < 30; i++) len[i] = 5;
            dm = inf_build(s->dt, len, 30);
        } else {
            int hlit, hdist, hclen, n, cm;
            iu8 cl[19];
            INF_BITS(hlit, 5); hlit += 257;
            INF_BITS(hdist, 5); hdist += 1;
            INF_BITS(hclen, 4); hclen += 4;
            for (i = 0; i < 19; i++) cl[i] = 0;
            for (i = 0; i < hclen; i++) {
                INF_FILL();
                INF_BITS(v, 3);
                cl[inf_order[i]] = (iu8)v;
            }
            cm = inf_build(s->dt, cl, 19);                      /* the distance table is free at this point */
            if (cm < 0) return 5;
            for (n = 0; n < hlit + hdist; ) {
                int e, sym, rep, prev;
                if (in >= s->lim) { s->in = in; s->cur = out; if (!s->more(s)) return 1; }
                INF_FILL();
                e = s->dt[bb & cm];
                if (!(e & 15)) return 6;
                bb >>= e & 15; bc -= e & 15;
                sym = e >> 4;
                if (sym < 16) { len[n++] = (iu8)sym; continue; }
                prev = 0;
                if (sym == 16) { if (!n) return 7; prev = len[n - 1]; INF_BITS(rep, 2); rep += 3; }
                else if (sym == 17) { INF_BITS(rep, 3); rep += 3; }
                else { INF_BITS(rep, 7); rep += 11; }
                if (n + rep > hlit + hdist) return 8;
                while (rep--) len[n++] = (iu8)prev;
            }
            lm = inf_build(s->lt, len, hlit);
            dm = inf_build(s->dt, len + hlit, hdist);
        }
        if (lm < 0 || dm < 0) return 9;
        for (;;) {
            int e, sym;
            if (in >= s->lim) { s->in = in; s->cur = out; if (!s->more(s)) return 1; }
            INF_FILL();
            e = s->lt[bb & lm];
            bb >>= e & 15; bc -= e & 15;
            sym = e >> 4;
            if (sym < 256) {
                if (!(e & 15)) return 10;
                if (out >= oend) return 3;
                *out++ = (iu8)sym;
                continue;
            }
            if (sym == 256) break;
            {
                iu32 l, d;
                const iu8 *src;
                sym -= 257;
                if (sym >= 29) return 11;
                INF_BITS(v, inf_lext[sym]);
                l = inf_lbase[sym] + v;
                INF_FILL();
                e = s->dt[bb & dm];
                if (!(e & 15)) return 12;
                bb >>= e & 15; bc -= e & 15;
                sym = e >> 4;
                if (sym >= 30) return 13;
                INF_FILL();
                INF_BITS(v, inf_dext[sym]);
                d = inf_dbase[sym] + v;
                if (d > (iu32)(out - s->out) || out + l > oend) return 14;
                src = out - d;
                do { *out++ = *src++; } while (--l);
            }
        }
    } while (!last);
    s->in = in;
    s->out = out;
    return 0;
}
