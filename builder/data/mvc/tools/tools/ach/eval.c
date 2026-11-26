/* eval.c: see eval.h */
#include "eval.h"

#ifdef RA_RAM_DECL
RA_RAM_DECL
#endif
#ifndef RA_RAM
#define RA_RAM ((const uint8_t*)0x80000000u)
#endif

static uint32_t read_mem(uint32_t m) {
	const uint8_t* p = RA_RAM + (m & 0x1FFFFFu);
	switch (MEM_SIZE(m)) {
	case 0: return p[0];
	case 1: return p[0] | (uint32_t)p[1] << 8;
	case 2: return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16;
	default: return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
	}
}

static uint32_t operand(uint32_t o) {
	const uint32_t i = o & 0x3FF;
	uint32_t v;
	switch (o >> 14) {
	case OPK_VALUE: v = ra_val[i]; break;
	case OPK_DELTA: v = ra_dlt[i]; break;
	default: return ra_const[o & 0x3FFF];
	}
	switch (o >> 10 & 15) {
	case PART_ALL: return v;
	case PART_LOW4: return v & 15;
	case PART_HIGH4: return v >> 4 & 15;
	case PART_BITCOUNT:
		v &= 0xFF;
		v = (v & 0x55) + (v >> 1 & 0x55);
		v = (v & 0x33) + (v >> 2 & 0x33);
		return (v & 15) + (v >> 4 & 15);
	default: return v >> ((o >> 10 & 15) - PART_BIT0) & 1;
	}
}

static int compare(uint32_t op, uint32_t a, uint32_t b) {
	switch (op) {
	case OP_EQ: return a == b;
	case OP_NE: return a != b;
	case OP_LT: return a < b;
	case OP_LE: return a <= b;
	case OP_GT: return a > b;
	case OP_GE: return a >= b;
	default: return 0;
	}
}

const uint8_t* ra_decode(const uint8_t* p, struct ra_cond* c) {
	const uint32_t t = p[0] & 15;
	c->type_op = p[0];
	c->lhs = (uint16_t)(p[1] | p[2] << 8);
	if (t == CT_ADD_SOURCE || t == CT_SUB_SOURCE) { c->rhs = 0; c->hits = 0; return p + 3; }
	c->rhs = (uint16_t)(p[3] | p[4] << 8);
	c->hits = p[5];
	return p + 6;
}

/* per trigger (rc_eval_state_t parts that outlive a group) */
static int has_hits, was_reset;
/* per group */
static int is_true, paused, and_next, or_next, reset_next;
static int32_t add_hits;
static uint32_t changed_prev = 0xFFFFFFFFu;
static int wstable = 1;                 /* an idempotent (pure 2) achievement was still WAITING in the last pass */

/* rc_condset_evaluate_condition_no_add_hits */
static int cond_no_add_hits(int valid, uint8_t* h, uint32_t target) {
	if (reset_next) {
		*h = 0;
		valid = 0;
	} else {
		valid = (valid & and_next) | or_next;
		if (valid) {
			has_hits = 1;
			if (target == 0) { if (*h != 0xFF) ++*h; }
			else if (*h < target) { ++*h; valid = *h == target; }
		} else if (*h) {
			has_hits = 1;
			valid = *h == target;
		}
	}
	and_next = 1; or_next = 0;
	return valid;
}

/* one part of a group (rc_test_condset_internal); returns the stream position after it */
static const uint8_t* run(const uint8_t* p, uint8_t* h, uint32_t n, int pure, int stop_on_pause) {
	uint32_t acc = 0;
	for (; n; n--, h++) {
		struct ra_cond c;
		uint32_t type;
		int valid;
		p = ra_decode(p, &c);
		type = c.type_op & 15;
		if (type == CT_ADD_SOURCE) { acc += operand(c.lhs); continue; }
		if (type == CT_SUB_SOURCE) { acc -= operand(c.lhs); continue; }
		valid = compare(c.type_op >> 4, acc + operand(c.lhs), operand(c.rhs));
		acc = 0;
		switch (type) {
		case CT_AND_NEXT: and_next = cond_no_add_hits(valid, h, c.hits); continue;
		case CT_OR_NEXT: or_next = cond_no_add_hits(valid, h, c.hits); continue;
		case CT_RESET_NEXT_IF: reset_next = cond_no_add_hits(valid, h, c.hits); continue;
		case CT_ADD_HITS: cond_no_add_hits(valid, h, c.hits); add_hits += *h; reset_next = 0; continue;
		case CT_SUB_HITS: cond_no_add_hits(valid, h, c.hits); add_hits -= *h; reset_next = 0; continue;
		default: break;
		}
		/* rc_condset_evaluate_condition */
		valid = cond_no_add_hits(valid, h, c.hits);
		if (add_hits != 0 && c.hits != 0) {
			const int32_t t = (int32_t)*h + add_hits;
			valid = (t >= 0 ? (uint32_t)t : 0) >= c.hits;
			add_hits = 0;
		}
		reset_next = 0;
		switch (type) {
		case CT_PAUSE_IF:
			if (valid) { paused = 1; is_true = 0; if (stop_on_pause) return 0; }
			else if (c.hits == 0) *h = 0;
			break;
		case CT_RESET_IF:
			if (valid) { was_reset = 1; is_true = 0; }
			break;
		default:                         /* standard, trigger */
			is_true &= valid;
			if (!is_true && pure) return 0;     /* nothing to update: stop at the first false one */
		}
	}
	return p;
}

/* rc_test_condset */
static int test_group(const struct ra_group* g, int pure) {
	const uint8_t* p = ra_code + g->code;
	uint8_t* h = ra_hit + g->hit;
	is_true = 1; paused = 0; and_next = 1; or_next = 0; reset_next = 0; add_hits = 0;
	if (g->n[0]) {                       /* pause chains: stop at the first true PauseIf */
		p = run(p, h, g->n[0], 0, 1);
		if (paused) return 0;
		h += g->n[0];
	}
	if (g->n[1]) { p = run(p, h, g->n[1], 0, 0); h += g->n[1]; }
	/* after a ResetIf (in this group or an earlier one) the trigger only resets: rcheevos
	   skips the hit-target part, and the rest changes nothing that is kept */
	if (was_reset) return 0;
	if (g->n[2]) { p = run(p, h, g->n[2], 0, 0); h += g->n[2]; }
	if (g->n[3] && !run(p, h, g->n[3], pure, 0)) return 0;
	return is_true;
}

static void clear_hits(const struct ra_ach* a) {
	const struct ra_group* g = &ra_group[a->group];
	const struct ra_group* l = &ra_group[a->group + a->ngroups - 1];
	uint32_t k, end = l->hit + l->n[0] + l->n[1] + l->n[2] + l->n[3];
	for (k = g->hit; k < end; k++) ra_hit[k] = 0;
}

void ra_eval_reset(void) {
	uint32_t i;
	changed_prev = 0xFFFFFFFFu;
	for (i = 0; i < ra_nmem; i++) ra_val[i] = ra_dlt[i] = 0;
	for (i = 0; i < ra_ncond; i++) ra_hit[i] = 0;
	for (i = 0; i < ra_nach; i++) { if (ra_st[i] != ST_OFF) ra_st[i] = ST_WAITING; ra_hh[i] = 0; }
}

uint32_t ra_eval_frame(uint8_t* out) {
	uint32_t i, n = 0, changed = 0, recent;
	for (i = 0; i < ra_nmem; i++) {
		const uint32_t v = read_mem(ra_mem[i]);
		if (v != ra_val[i]) changed |= i < 31 ? 1u << i : 1u << 31;
		ra_dlt[i] = ra_val[i]; ra_val[i] = v;
	}
	recent = changed | changed_prev;
	changed_prev = changed;
	if (!recent && !ra_impure && !wstable) return 0;      /* nothing read changed in two frames: every result stays */
	wstable = 0;
	for (i = 0; i < ra_nach; i++) {
		const struct ra_ach* a = &ra_ach[i];
		int ret;
		const int pure = a->pure == 1;
		if (ra_st[i] >= ST_TRIGGERED || (a->pure && !(a->deps & recent) && (pure || ra_st[i] != ST_WAITING))) continue;
		has_hits = was_reset = 0;
		ret = test_group(&ra_group[a->group], pure);
		if (a->ngroups > 1 && !(pure && !ret)) {
			uint32_t j;
			int sub = 0;
			for (j = 1; j < a->ngroups && !(sub && pure); j++) sub |= test_group(&ra_group[a->group + j], pure);
			ret &= sub;
		}
		if (a->pure == 2 && ra_st[i] == ST_WAITING) wstable = 1;
		if (was_reset) {
			clear_hits(a);
			if (ra_hh[i]) { ra_hh[i] = 0; continue; }       /* state unchanged */
			ra_st[i] = ST_ACTIVE;
		} else if (ret) {
			if (ra_st[i] == ST_WAITING) { clear_hits(a); ra_hh[i] = 0; continue; }
			ra_st[i] = ST_TRIGGERED;
			out[n++] = (uint8_t)i;
		} else {
			ra_hh[i] = (uint8_t)has_hits;
			ra_st[i] = ST_ACTIVE;
		}
	}
	return n;
}
