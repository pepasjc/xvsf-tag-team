/* meta.h: achievement texts and points (gen/set.c, tools/ach/setc.py) */
#pragma once
#include <stdint.h>

extern const uint16_t ra_total_points;
extern const uint8_t ra_points[];
/* per achievement two NUL-terminated strings, title and description (lines split by '\n');
   bytes 0x80.. stand for entry (byte - 0x80) of the phrase dictionary ra_dict */
extern const uint8_t ra_text[];
extern const char ra_dict[];
