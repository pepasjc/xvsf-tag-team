/* host test of inflate.h:  inftest packed.bin original.bin   (input arrives in 2048-byte steps) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "inflate.h"
static const iu8 *base; static long total, arrived;
static int more(struct inf *s)
{
    if (arrived >= total) { if (s->lim > base + total + 4096) return 0; s->lim = base + total + 8192; return 1; }
    arrived += 2048; if (arrived > total) arrived = total;
    s->lim = arrived >= total ? base + total + 8192 : base + arrived - INF_MARGIN;
    return 1;
}
int main(int argc, char **argv)
{
    FILE *f = fopen(argv[1], "rb"); static iu8 *in, *out, *ref; long n, m; struct inf s; int r;
    static iu16 lt[32768], dt[32768];
    fseek(f, 0, 2); n = ftell(f); fseek(f, 0, 0); in = calloc(n + 16384, 1); fread(in, 1, n, f); fclose(f);
    f = fopen(argv[2], "rb"); fseek(f, 0, 2); m = ftell(f); fseek(f, 0, 0); ref = malloc(m); fread(ref, 1, m, f); fclose(f);
    out = malloc(m + 16);
    base = in; total = n; arrived = 0;
    s.in = in; s.lim = in; s.out = out; s.oend = out + m; s.more = more; s.lt = lt; s.dt = dt;
    r = inf_run(&s);
    if (r || s.out - out != m || memcmp(out, ref, m)) { printf("FAIL %s: error %d, %ld of %ld bytes\n", argv[1], r, (long)(s.out - out), m); return 1; }
    printf("ok %s: %ld -> %ld\n", argv[1], n, m);
    return 0;
}
