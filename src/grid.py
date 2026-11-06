"""Square grid (1 km cells, columns A..I west->east, rows 1..12 north->south).

* texture overlay: line / cell-id masks (core + halo), faded out over the open sea;
* vector pieces: thin line ribbons + the same cell id outlines as the texture (textgeo.py).
"""
import math
import numpy as np
import cv2
from PIL import Image, ImageDraw

from layers import W, H, X0, Y0, MPP

CELL = 1000.0
GX0, GX1 = -4000.0, 5000.0      # 9 columns
GY0, GY1 = 8000.0, -4000.0      # 12 rows
COLS = "ABCDEFGHI"
LINE_W_PX = 3
LINE_W_M = 5.0
ID_STYLE = (34, "SemiBold", 4)      # px size, Bahnschrift style, halo px


def px(x, y):
    return (x - X0) / MPP, (Y0 - y) / MPP


def cells():
    for ci in range(int((GX1 - GX0) / CELL)):
        for ri in range(int((GY0 - GY1) / CELL)):
            x0, y0 = GX0 + ci * CELL, GY0 - ri * CELL
            yield "%s%d" % (COLS[ci], ri + 1), x0, y0


def cell_has_land(land, x0, y0):
    a = px(x0, y0)
    b = px(x0 + CELL, y0 - CELL)
    sub = land[max(0, int(a[1])):int(b[1]), max(0, int(a[0])):int(b[0])]
    return sub.size > 0 and sub.max() > 0.5


def id_shapes(land, busy=None):
    """Cell ids (Bahnschrift outlines, map px) in a corner of every cell that has land, kept clear
    of the district / road names (busy: uint8 mask of them). [(name, core, halo)]"""
    import textgeo as tg
    size, style, sw = ID_STYLE
    cw = CELL / MPP
    out = []
    for name, x0, y0 in cells():
        if not cell_has_land(land, x0, y0):
            continue
        a = px(x0, y0)
        sh = tg.text_shape(name, size, style, tracking=0.04, align="left")
        tw = sh.bounds[2] + 8
        spots = [(a[0] + 14, a[1] + 26), (a[0] + cw - 14 - tw, a[1] + 26),
                 (a[0] + 14, a[1] + cw - 30), (a[0] + cw - 14 - tw, a[1] + cw - 30)]
        pos = spots[0]
        if busy is not None:
            for sx, sy in spots:
                x_, y_ = int(sx), int(sy - 22)
                if not busy[max(0, y_):y_ + 44, max(0, x_):x_ + int(tw)].any():
                    pos = (sx, sy)
                    break
        out.append((name, tg.place(sh, pos[0], pos[1]), tg.place(tg.halo_of(sh, sw), pos[0], pos[1])))
    return out


def texture_masks(alpha, ids):
    """(core, halo) float masks 0..1 at map resolution: lines (faded over the sea) + cell ids."""
    import textgeo as tg
    core = Image.new("L", (W, H), 0)
    halo = Image.new("L", (W, H), 0)
    dc, dh = ImageDraw.Draw(core), ImageDraw.Draw(halo)
    for k in range(int((GX1 - GX0) / CELL) + 1):
        x, _ = px(GX0 + k * CELL, 0)
        dh.line((x, 0, x, H), fill=255, width=LINE_W_PX + 4)
        dc.line((x, 0, x, H), fill=255, width=LINE_W_PX)
    for k in range(int((GY0 - GY1) / CELL) + 1):
        _, y = px(0, GY0 - k * CELL)
        dh.line((0, y, W, y), fill=255, width=LINE_W_PX + 4)
        dc.line((0, y, W, y), fill=255, width=LINE_W_PX)
    # lines fade out over the open sea together with the map itself
    fade = np.clip(alpha * 1.6, 0, 1)
    core = np.asarray(core).astype(np.float32) / 255 * fade * 0.55
    halo = np.asarray(halo).astype(np.float32) / 255 * fade * 0.35
    ci = tg.rasterize([c for _, c, _ in ids], (W, H)).astype(np.float32) / 255
    hi = tg.rasterize([h for _, _, h in ids], (W, H)).astype(np.float32) / 255
    return np.maximum(core, ci), np.maximum(halo, hi)
