/*
	eval.h: a small RetroAchievements trigger evaluator for the built-in achievements of the
	tag hacks (XvSF, MSHvSF, MvC). Derived from the Beyond the Beyond / RE2 Ultimate one.

	Follows rcheevos 12.5 (trigger.c, condset.c) for the features tools/ach/setc.py accepts:
	  - memory references: 8/16/24/32-bit, bit 0-7, nibbles, bit count; value and delta;
	  - flags: PauseIf, ResetIf, AddSource, SubSource, AndNext, OrNext, ResetNextIf,
	    AddHits, SubHits, Trigger; hit counts; core group + alt groups;
	  - rcheevos's order inside a group: pause chains first (stop at the first true one),
	    then reset chains, hit-target chains, the rest (setc.py stores the conditions in
	    that order and the size of each part);
	  - the WAITING state (a trigger that is true when it is activated fires only after it
	    has been false once).
	tools/ach/host/diff.c checks it against rcheevos frame by frame.

	Cost: an achievement is "pure" when nothing in it keeps state (no hit targets, ResetIf,
	AddHits/SubHits, ResetNextIf). A pure achievement depends only on this frame's values
	and deltas of its own memory references; when none of them changed in this frame or
	the last, its result (and state) is the same as last frame and it is skipped. Testing a
	pure group also stops at its first false condition.
*/
#pragma once
#include <stdint.h>

/* memory reference: address (21 bits) | size << 24 (0 byte, 1 16-bit, 2 24-bit, 3 32-bit) */
#define MEM_SIZE(m) ((m) >> 24 & 3)

/* operand: kind << 14 | part << 10 | index (memory reference or constant) */
#define OPK_CONST 0
#define OPK_VALUE 1
#define OPK_DELTA 2
enum { PART_ALL, PART_BIT0, PART_BIT7 = PART_BIT0 + 7, PART_LOW4, PART_HIGH4, PART_BITCOUNT };

enum { CT_STANDARD, CT_ADD_SOURCE, CT_SUB_SOURCE, CT_AND_NEXT, CT_OR_NEXT, CT_RESET_NEXT_IF,
       CT_ADD_HITS, CT_SUB_HITS, CT_RESET_IF, CT_PAUSE_IF, CT_TRIGGER };
enum { OP_NONE, OP_EQ, OP_NE, OP_LT, OP_LE, OP_GT, OP_GE };

/* a condition in the code stream: type | op << 4, lhs (u16 LE), then for all but AddSource /
   SubSource: rhs (u16 LE), hit target (u8) */
struct ra_cond { uint8_t type_op, hits; uint16_t lhs, rhs; };
/* group: first byte in ra_code, first hit count, then the number of conditions in each part
   (pause, reset, hit target, other), in that order in the stream */
struct ra_group { uint16_t code, hit; uint8_t n[4]; };
/* achievement: first group, number of groups, pure flag, memory references read (bit i =
   reference i; bit 31 also stands for every reference from 31 on) */
struct ra_ach { uint16_t group; uint8_t ngroups, pure; uint32_t deps; };   /* pure: 1 stateless, 2 idempotent (setc.py), 0 */

/* the compiled set (gen/set.c) */
extern const uint16_t ra_nmem, ra_ncond, ra_nach, ra_nconst, ra_impure;
extern const uint32_t ra_mem[];
extern const uint32_t ra_const[];
extern const uint8_t ra_code[];
extern const struct ra_group ra_group[];
extern const struct ra_ach ra_ach[];

#define ST_WAITING   0
#define ST_ACTIVE    1
#define ST_TRIGGERED 2
#define ST_OFF       3   /* unlocked earlier: not evaluated */
extern uint32_t ra_val[], ra_dlt[];
extern uint8_t ra_hit[];                      /* saturates at 255 */
extern uint8_t ra_st[], ra_hh[];

void ra_eval_reset(void);
/* one frame: update the memory references, test every achievement; returns how many
   triggered (their indices in out[]) */
uint32_t ra_eval_frame(uint8_t* out);
const uint8_t* ra_decode(const uint8_t* p, struct ra_cond* c);
