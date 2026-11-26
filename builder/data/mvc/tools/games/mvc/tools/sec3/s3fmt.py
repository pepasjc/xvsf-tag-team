"""SEC3 (MvC per-frame box data, DSP section 3) format model, from the engine readers (rc2 RAM):
  consumer = 0x8008cb60 per part (at 0x8008cca4) + 0x8008b538; pointer ctx+0x50 = 0x8009c210[obj+0x73] + obj+0x3e.
item u16 (LE):  0x0000 -> nothing (not consumed; ends the record for every later part)
                low byte 0xff -> consumed, 2 B, no box ("skip")
                low byte == part index -> consumed: 2 B + box data; mode = bits 14-15, mask = bits 10-13 (4 boxes)
                   mode 0: none, 1: 1 B per box (signed nibbles x lo, y hi), 2: 2 x s8, 3: 2 x s16
                low byte other -> not consumed (item for a later part)
first item: bit 0x100 / 0x200 = flip x / y of the boxes (0x80092b00 / 0x2b04)."""
import struct
BOXB = {0: 0, 1: 1, 2: 2, 3: 4}


def item_len(v):
    if v & 0xff == 0xff: return 2
    m = v >> 14; k = bin((v >> 10) & 15).count("1")
    return 2 + BOXB[m] * k


def walk_engine(s3, off, nparts):
    """exactly what the engine reads for a group with nparts parts -> (end, items[(pos, u16)]); end = first byte not read
    (a final 0x0000 / foreign item is read but not consumed: counted as read: 'read_end')"""
    p = off; items = []; read_end = off
    for i in range(nparts):
        while True:                       # one u16 look per part; 0xff consumes one item and moves to the NEXT part
            if p + 2 > len(s3): return p, max(read_end, p), items, "past"
            v = s3[p] | s3[p + 1] << 8; read_end = max(read_end, p + 2)
            if v == 0: break
            if v & 0xff == 0xff: items.append((p, v)); p += 2; break
            if v & 0xff == i: n = item_len(v); items.append((p, v)); p += n; read_end = max(read_end, p); break
            break
    return p, read_end, items, "ok"


def tile_seq(s3):
    """sequential model: records = items until a 0x0000 terminator (stored).  -> list of (start, end incl. terminator)"""
    out = []; p = 0
    while p + 2 <= len(s3):
        st = p; last = -1
        while p + 2 <= len(s3):
            v = s3[p] | s3[p + 1] << 8
            if v == 0: p += 2; break
            p += item_len(v)
        out.append((st, p))
    return out
