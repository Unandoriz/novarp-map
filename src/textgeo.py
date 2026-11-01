"""Text as geometry: Bahnschrift glyph outlines -> polygons (map px, y down).

The same polygons are rasterised into the texture overlays and triangulated into the vector
minimap tiles, so the labels and grid ids look identical at every zoom level.
"""
import math
import numpy as np
import cv2
import mapbox_earcut
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.pens.basePen import BasePen
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import affinity

FONT = "C:/Windows/Fonts/bahnschrift.ttf"
_fonts = {}


def _font(style):
    if style not in _fonts:
        f = TTFont(FONT)
        coords = None
        for inst in f["fvar"].instances:
            if f["name"].getDebugName(inst.subfamilyNameID) == style:
                coords = dict(inst.coordinates)
        if coords is None:
            raise KeyError(style)
        f = instancer.instantiateVariableFont(f, coords)
        _fonts[style] = (f, f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _fonts[style]


class _FlatPen(BasePen):
    """Flattens quadratic / cubic segments; contours in font units (y up)."""

    def __init__(self, glyphset, tol):
        BasePen.__init__(self, glyphset)
        self.tol = tol
        self.rings, self.cur = [], []

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _steps(self, pts):
        d = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        return max(2, min(16, int(math.ceil(math.sqrt(d / (self.tol * 8))))))

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        n = self._steps((p0, p1, p2))
        for i in range(1, n + 1):
            t = i / n
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            self.cur.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        n = self._steps((p0, p1, p2, p3))
        for i in range(1, n + 1):
            t = i / n
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            self.cur.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                             a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))

    def _closePath(self):
        if len(self.cur) >= 3:
            self.rings.append(self.cur)
        self.cur = []

    _endPath = _closePath


def _signed_area(r):
    a = np.asarray(r)
    return 0.5 * float(np.sum(a[:-1, 0] * a[1:, 1] - a[1:, 0] * a[:-1, 1]) + a[-1, 0] * a[0, 1] - a[0, 0] * a[-1, 1])


def glyph_shape(ch, style, size):
    """Glyph outline at `size` px (em), origin on the baseline, y down. Non-zero fill rule:
    every hole is cut from the smallest outer contour around it, then everything is united."""
    f, gs, cmap, hmtx, upm = _font(style)
    name = cmap.get(ord(ch))
    if name is None:
        raise KeyError(ch)
    k = size / upm
    pen = _FlatPen(gs, 0.12 / k)
    gs[name].draw(pen)
    outers, holes = [], []
    for r in pen.rings:
        (outers if _signed_area(r) < 0 else holes).append(r)     # TrueType: outer contours run clockwise
    polys = [[Polygon(r).buffer(0), []] for r in outers]
    for h in holes:
        hp = Polygon(h).buffer(0)
        best = None
        for p in polys:      # the hole's own contour must enclose it entirely (Ф: the stem crosses the hole)
            if p[0].buffer(1.0).contains(hp) and (best is None or p[0].area < best[0].area):
                best = p
        if best is not None:
            best[1].append(hp)
    parts = [p.difference(unary_union(hs)) if hs else p for p, hs in polys]
    shape = unary_union(parts) if parts else Polygon()
    shape = affinity.scale(shape, k, -k, origin=(0, 0))
    return shape, hmtx[name][0] * k


def metrics(size):
    """(ascent, descent) in px, like PIL's FreeTypeFont.getmetrics() for Bahnschrift."""
    return int(round(1626 * size / 2048)), int(math.ceil(422 * size / 2048))


def text_shape(text, size, style, tracking=0.08, align="center"):
    """Text block (multi-line with \\n) around (0, 0): align "center" = centred on the block,
    "left" = left edge at x=0, vertically centred like the old PIL layout (y down)."""
    asc, desc = metrics(size)
    lh = int((asc + desc) * 0.92)
    lines = text.split("\n")
    y = -lh * len(lines) / 2
    parts = []
    for ln in lines:
        adv = []
        for ch in ln:
            adv.append(glyph_shape(ch, style, size)[1] if ch != " " else _space(style, size))
        w = sum(adv) + size * tracking * (len(ln) - 1)
        x = -w / 2 if align == "center" else 0.0
        for ch, a in zip(ln, adv):
            if ch != " ":
                g = glyph_shape(ch, style, size)[0]
                parts.append(affinity.translate(g, x, y + asc))
            x += a + size * tracking
        y += lh
    return unary_union(parts)


def _space(style, size):
    f, gs, cmap, hmtx, upm = _font(style)
    return hmtx[cmap[ord(" ")]][0] * size / upm


def halo_of(shape, width):
    """Outline of `width` px around the text (like PIL stroke_width), small holes filled."""
    h = shape.buffer(width, quad_segs=3, join_style="round")
    out = []
    for p in getattr(h, "geoms", [h]):
        holes = [r for r in p.interiors if Polygon(r).area > (width * 2.2) ** 2]
        out.append(Polygon(p.exterior, holes))
    return unary_union(out)


def place(shape, x, y, angle=0.0):
    """Rotate by `angle` degrees (image coords, clockwise on screen) and move to (x, y)."""
    if angle:
        shape = affinity.rotate(shape, angle, origin=(0, 0))
    return affinity.translate(shape, x, y)


# ------------------------------------------------------------------ raster
def rasterize(shapes, size, ss=4):
    """Anti-aliased coverage mask (uint8, H x W) of shapely polygons in px coords."""
    W_, H_ = size
    out = np.zeros((H_, W_), np.uint8)
    for shp in shapes:
        if shp.is_empty:
            continue
        x0, y0, x1, y1 = shp.bounds
        bx0, by0 = max(0, int(x0) - 2), max(0, int(y0) - 2)
        bx1, by1 = min(W_, int(x1) + 3), min(H_, int(y1) + 3)
        if bx1 <= bx0 or by1 <= by0:
            continue
        big = np.zeros(((by1 - by0) * ss, (bx1 - bx0) * ss), np.uint8)
        for p in getattr(shp, "geoms", [shp]):
            rings = [p.exterior] + list(p.interiors)
            pts = [np.round((np.asarray(r.coords)[:, :2] - (bx0, by0)) * ss * 16).astype(np.int32) for r in rings]
            cv2.fillPoly(big, pts, 255, lineType=cv2.LINE_8, shift=4)
        small = cv2.resize(big, (bx1 - bx0, by1 - by0), interpolation=cv2.INTER_AREA)
        sub = out[by0:by1, bx0:bx1]
        np.maximum(sub, small, out=sub)
    return out


# ------------------------------------------------------------------ triangles
def triangulate(shape, simplify=0.0):
    """(verts N x 2 float, tris list of (a, b, c)) of a (multi)polygon."""
    if simplify:
        shape = shape.simplify(simplify, preserve_topology=True)
    verts, tris = [], []
    for p in getattr(shape, "geoms", [shape]):
        if p.is_empty or p.area <= 0:
            continue
        rings = [np.asarray(p.exterior.coords)[:-1, :2]] + [np.asarray(r.coords)[:-1, :2] for r in p.interiors]
        rings = [r for r in rings if len(r) >= 3]
        if not rings:
            continue
        v = np.concatenate(rings).astype(np.float64)
        ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        idx = mapbox_earcut.triangulate_float64(v, ends).reshape(-1, 3)
        base = len(verts)
        verts.extend(map(tuple, v))
        for a, b, c in idx:
            cr = (v[b, 0] - v[a, 0]) * (v[c, 1] - v[a, 1]) - (v[b, 1] - v[a, 1]) * (v[c, 0] - v[a, 0])
            if cr > 0:
                tris.append((base + int(a), base + int(b), base + int(c)))
            elif cr < 0:                      # counter-clockwise in the input coordinates
                tris.append((base + int(a), base + int(c), base + int(b)))
    return np.asarray(verts, float).reshape(-1, 2), tris
