"""Install-time plan for the vector minimap tiles (x64e.rpf/levels/gta5/minimap.rpf).

The installer rebuilds the 65 tiles from the player's own vanilla files, for the chosen
theme and options. This module prepares everything theme/option dependent:

  * colour look-up tables per theme for the vanilla vertex colours;
  * extra geometry per tile and option combo (grid x labels): hunting zones, city borders,
    grid lines + cell ids, district / road labels (the same glyph outlines as the texture
    overlays, textgeo.py), all clipped to the tile's cell;
  * the draw order of the tile.

Draw order. Every vanilla drawable is one model with one geometry, and the game sorts the
drawables of the visible tiles by their bounds relative to the camera, which reshuffles our
overlays against the roads as the map moves. So every tile we touch gets its land, building
and road models in one drawable, in a fixed order with growing heights: land (+ zone fills),
then buildings / roads, and last the smallest road model, which also carries our lines and
text (halo before text). The tile's dictionary then holds that drawable and the sea ones.
The sea drawables stay exactly as they are (the game stops drawing them once they are merged
or extended), so tiles of only sea are never touched: their cells belong to the nearest tile
with land, whose drawable draws our things there.

Extended buffers go into new 8..64 KB pages inserted into the resource's page layout (see
Relayout).

apply_plan() is the reference implementation of what the installer does (Installer side:
VectorPlan.cs); main() writes build/vector_plan.bin and expected outputs for the C# check.
"""
import glob
import json
import math
import os
import pickle
import struct
import sys
import zlib
import numpy as np
from shapely import affinity

from ydd_zones import (BASE, P, u64, read_rsc, drawable_info, vanilla_geometries, zone_shapes, px_to_world)
from layers import X0, Y0, MPP, smoothstep
import grid as grid_mod
import textgeo

MAX_V, MAX_I = 4096, 16384       # per extended geometry: vertex buffer <= 64 KB, index buffer <= 32 KB
THEME_ORDER = ["dark", "light", "winter", "halloween"]
# Vanilla heights: sea -12, land 0, buildings 6, roads 12. Ours: zone fill between land and
# buildings, the rest above the roads (only the low layers are depth sorted in game; the order
# of the models / triangles decides the rest, see above).
LAYERS = ["zone_fill", "zone_line", "border", "grid_line", "grid_text", "grid_halo", "label", "label_halo", "label_water"]
LZ = {"zone_fill": 3.0, "zone_line": 18.0, "border": 18.0, "grid_line": 24.0, "grid_halo": 30.0, "grid_text": 36.0,
      "label_halo": 30.0, "label": 36.0, "label_water": 36.0, "relief": 1.0}
CELL_X0, CELL_W, CELL_Y0, CELL_H = -4500.0, 1175.0, 8000.0, 1388.0   # minimap_A_B: x cell A, y cell B (down)


# ------------------------------------------------------------------ colours
def flat_factor(T):
    return 1 + (math.sin(math.radians(45)) - 0.66) * T["shade_strength"] * 1.6


def luts(T, relief=False):
    """(land_lut, water_lut): 256 x 3 uint8, indexed by the vanilla grey level (r+g+b)//3."""
    land_c = np.array(T["land_low"], float) * flat_factor(T) if relief else np.array(T["land"], float)
    land_c = tuple(int(round(v)) for v in land_c)
    deep, shore = np.array(T["ocean_deep"], float), np.array(T["ocean_shore"], float)
    land_lut = np.zeros((256, 3), np.uint8)
    water_lut = np.zeros((256, 3), np.uint8)
    for lum in range(256):
        if lum >= 146:
            c = T["major"]
        elif lum >= 90:
            c = T["road"]
        elif 27 <= lum <= 31:
            c = land_c
        else:
            c = T["built"]
        land_lut[lum] = np.clip(c, 0, 255)
        t = float(np.clip((lum - 85) / (220 - 85), 0, 1)) ** 1.3
        water_lut[lum] = np.clip(np.round(deep + (shore - deep) * t), 0, 255)
    return land_lut, water_lut


def layer_colours(T):
    land = np.array(T["land"], float)
    zf = land + (np.array(T["zone_fill"], float) - land) * T["zone_fill_a"] * 1.1
    gl = land + (np.array(T["grid"], float) - land) * 0.45
    out = {"zone_fill": zf, "zone_line": T["zone_line"], "border": T["border"], "grid_line": gl, "grid_text": T["grid"],
           "grid_halo": T["grid_halo"], "label": T["label"], "label_halo": T["label_stroke"], "label_water": T["label_water"]}
    return {k: tuple(int(round(float(c))) for c in v) for k, v in out.items()}


# ------------------------------------------------------------------ overlay shapes (world coords)
def _world(shape):
    return affinity.affine_transform(shape, [MPP, 0, 0, -MPP, X0, Y0])


def border_shape():
    """Dashed city borders: one (multi)polygon of all dashes."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    dashes = []
    dash, gap, width = 60.0, 40.0, 6.0
    for pls in json.load(open("build/borders.json")).values():
        for pl in pls:
            pts = px_to_world(pl)
            seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            dist = np.concatenate([[0], np.cumsum(seg)])
            t = 0.0
            while t < dist[-1]:
                t1 = min(t + dash, dist[-1])
                ts = np.linspace(t, t1, 4)
                line = np.stack([np.interp(ts, dist, pts[:, 0]), np.interp(ts, dist, pts[:, 1])], 1)
                if np.linalg.norm(line[-1] - line[0]) > 1:
                    dashes.append(LineString(line).buffer(width / 2, cap_style="flat", join_style="mitre", mitre_limit=2))
                t += dash + gap
    return unary_union(dashes)


def grid_line_shape():
    """All grid lines as one polygon (thin rectangles, the cells are its holes)."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    g = grid_mod
    w = g.LINE_W_M / 2
    rects = [box(g.GX0 + k * g.CELL - w, g.GY1, g.GX0 + k * g.CELL + w, g.GY0) for k in range(int((g.GX1 - g.GX0) / g.CELL) + 1)]
    rects += [box(g.GX0, g.GY0 - k * g.CELL - w, g.GX1, g.GY0 - k * g.CELL + w) for k in range(int((g.GY0 - g.GY1) / g.CELL) + 1)]
    return unary_union(rects)


def grid_visible_area():
    """Where the texture grid lines are at least half visible, as a world polygon: they fade out
    over the open sea with the map's own alpha (grid.texture_masks: clip(alpha * 1.6))."""
    import cv2
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from render import base
    L = dict(np.load("build/layers.npz"))
    _, alpha = base("dark", L, relief=False)
    m = (np.clip(alpha * 1.6, 0, 1) >= 0.5).astype(np.uint8)
    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    for i, c in enumerate(cs):
        if hier[0][i][3] >= 0 or len(c) < 3:
            continue
        holes = [cs[j][:, 0, :] for j in range(len(cs)) if hier[0][j][3] == i and len(cs[j]) >= 3]
        p = Polygon(c[:, 0, :], holes).buffer(0)
        if p.area > 4:
            polys.append(p)
    return _world(unary_union(polys)).simplify(4.0)


def overlay_units():
    """[(group, name, [(shape, layer)])], in drawing order. group: zones / borders / lines / ids /
    labels (lines and ids only with the grid option, labels only with the labels option)."""
    geo = pickle.load(open("build/text_geo.pkl", "rb"))
    units = []
    for i, (shape, kind) in enumerate(zone_shapes()):
        units.append(("zones", "zone%d" % i, [(shape, "zone_fill" if kind == "fill" else "zone_line")]))
    units.append(("borders", "borders", [(border_shape(), "border")]))
    # like on the textures, the lines end over the open sea (where the texture ones fade out)
    units.append(("lines", "grid", [(grid_line_shape().intersection(grid_visible_area()), "grid_line")]))

    def w(shape, tol_px):
        return _world(shape).simplify(tol_px * MPP, preserve_topology=True)

    for name, core, halo in geo["ids"]:
        units.append(("ids", name, [(w(halo, 1.0), "grid_halo"), (w(core, 0.35), "grid_text")]))
    for d in geo["labels"]:
        if d["kind"] == "water":
            units.append(("labels", d["text"], [(w(d["core"], 0.35), "label_water")]))
        else:
            units.append(("labels", d["text"], [(w(d["halo"], 1.0), "label_halo"), (w(d["core"], 0.35), "label")]))
    return units


def _ab(name):
    return tuple(map(int, name[len("minimap_"):-len(".ydd")].split("_")))


def tile_regions(names, sea_only):
    """{tile: polygon} partition of the plane: every grid cell (one ring beyond the tiles too,
    reaching far out) belongs to the nearest tile that has land / roads (breadth first over the
    grid, deterministic), so no two tiles ever draw our things over the same spot."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    land_tiles = sorted(_ab(n) for n in names if n not in sea_only)
    a0, a1 = min(a for a, _ in land_tiles) - 1, max(a for a, _ in land_tiles) + 1
    b0, b1 = min(b for _, b in land_tiles) - 1, max(b for _, b in land_tiles) + 1
    for n in names:
        a, b = _ab(n)
        a0, a1, b0, b1 = min(a0, a - 1), max(a1, a + 1), min(b0, b - 1), max(b1, b + 1)
    owner = {t: t for t in land_tiles}
    queue = list(land_tiles)
    while queue:
        nxt = []
        for a, b in queue:
            for c in ((a - 1, b), (a + 1, b), (a, b - 1), (a, b + 1)):
                if a0 <= c[0] <= a1 and b0 <= c[1] <= b1 and c not in owner:
                    owner[c] = owner[(a, b)]
                    nxt.append(c)
        queue = nxt
    far = 1e5
    cells = {}
    for (a, b), t in owner.items():
        x0, x1 = CELL_X0 + CELL_W * a, CELL_X0 + CELL_W * (a + 1)
        y1, y0 = CELL_Y0 - CELL_H * b, CELL_Y0 - CELL_H * (b + 1)
        if a == a0: x0 -= far
        if a == a1: x1 += far
        if b == b0: y1 += far
        if b == b1: y0 -= far
        cells.setdefault(t, []).append(box(x0, y0, x1, y1))
    return {"minimap_%d_%d.ydd" % t: unary_union(bs) for t, bs in cells.items()}


def clip_pieces(parts, region):
    """[(shape, layer)] clipped to the region -> pieces dict(layer, v, t) (counter-clockwise triangles)."""
    b = region
    out = []
    for shape, layer in parts:
        if shape.is_empty or not shape.intersects(b):
            continue
        c = shape.intersection(b)
        c = c if c.geom_type in ("Polygon", "MultiPolygon") else \
            unary_union_polys(c)
        v, t = textgeo.triangulate(c)
        if len(t):
            out.append(dict(layer=layer, v=v, t=t))
    return out


def unary_union_polys(g):
    from shapely.ops import unary_union
    return unary_union([p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")])


# ------------------------------------------------------------------ relief (currently unused)
def relief_fields():
    """Theme independent relief fields: q (shading, factor = 1 + q * shade_strength) and tint."""
    import cv2
    from render import terrain
    L = dict(np.load("build/layers.npz"))
    h, shade = terrain(L)
    built = L["built"].astype(np.float32)
    road = L["road"].astype(np.float32)
    urban = cv2.GaussianBlur(np.clip(built + road, 0, 1), (0, 0), 30)
    q = (shade - 0.66) * (1 - smoothstep(0.12, 0.4, urban) * 0.85) * 1.6
    q = cv2.GaussianBlur(q.astype(np.float32), (0, 0), 12)
    tint = cv2.GaussianBlur(smoothstep(5, 120, h).astype(np.float32), (0, 0), 12)
    return dict(q=q, tint=tint, land=L["land"].astype(np.float32))


def relief_mesh(box, step, F):
    x0, y0, x1, y1 = box
    xs = np.arange(x0, x1 + step, step)
    ys = np.arange(y0, y1 + step, step)
    H_, W_ = F["land"].shape

    def pix(x, y):
        return (min(max(int((x - X0) / MPP), 0), W_ - 1), min(max(int((Y0 - y) / MPP), 0), H_ - 1))

    val = {}
    for i in range(len(xs)):
        for j in range(len(ys)):
            c, r = pix(xs[i], ys[j])
            val[(i, j)] = (float(F["q"][r, c]), float(F["tint"][r, c]))
    nodes, verts, attrs, tris = {}, [], [], []

    def node(i, j):
        if (i, j) not in nodes:
            nodes[(i, j)] = len(verts)
            verts.append((xs[i], ys[j]))
            attrs.append(val[(i, j)])
        return nodes[(i, j)]

    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            ca, cb = pix(xs[i], ys[j + 1]), pix(xs[i + 1], ys[j])
            blk = F["land"][ca[1]:cb[1] + 1, ca[0]:cb[0] + 1]
            if blk.size == 0 or blk.min() < 0.99:
                continue
            corners = [val[(i, j)], val[(i + 1, j)], val[(i, j + 1)], val[(i + 1, j + 1)]]
            if max(abs(q) * 0.5 for q, _ in corners) < 0.025 and max(t for _, t in corners) < 0.15:
                continue
            a, b, c, d = node(i, j), node(i + 1, j), node(i, j + 1), node(i + 1, j + 1)
            tris += [(a, b, d), (a, d, c)]
    return np.array(verts, float).reshape(-1, 2), tris, np.array(attrs, float).reshape(-1, 2)


def relief_colours(attrs, T):
    low, hi = np.array(T["land_low"], float), np.array(T["land"], float)
    f = np.clip(1 + attrs[:, 0] * T["shade_strength"], 0.74, 1.16)
    c = (low[None, :] + (hi - low)[None, :] * attrs[:, 1:2]) * f[:, None]
    return np.clip(np.round(c), 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ plan
def tile_box(s):
    xs, ys = [], []
    for off, n, stride in vanilla_geometries(s):
        a = np.frombuffer(s, np.float32, n * stride // 4, off).reshape(n, stride // 4)
        xs.append(a[:, 0]); ys.append(a[:, 1])
    xs, ys = np.concatenate(xs), np.concatenate(ys)
    return (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))


def draw_order(hosts):
    """(order of drawable indices, zone fill host, overlay host) for a tile, None for tiles of
    only sea: land, then the rest by height; the overlay host (smallest of the top drawables)
    goes last, so heights grow along the order. The sea drawables are not part of it."""
    land = sorted([h for h in hosts if abs(h["z"]) < 0.5], key=lambda h: h["index"])
    top = sorted([h for h in hosts if h["z"] >= 0.5], key=lambda h: (h["z"], h["index"]))
    if not land and not top:
        return None
    over = min(top, key=lambda h: (h["n"], h["index"])) if top else land[-1]
    zone = land[-1] if land else None
    order = [h for h in land + top if h is not over] + [over]
    return [h["index"] for h in order], zone, over


def build_plan():
    """combos[(grid, labels)][tile] = dict(order=[drawable index], hosts=[(drawable index, pieces)])."""
    units = overlay_units()
    files = sorted(glob.glob("files/game/minimap_ydd/minimap_*.ydd"))
    tiles = {os.path.basename(p): read_rsc(p)["sys"] for p in files}
    sea_only = {n for n, s in tiles.items() if draw_order(drawable_info_indexed(s)) is None}
    regions = tile_regions(set(tiles), sea_only)
    combos = {(g, l): {} for g in (0, 1) for l in (0, 1)}
    for name, s in sorted(tiles.items()):
        if name in sea_only:
            print(name, "only sea: untouched")
            continue
        hosts = drawable_info_indexed(s)
        assert len(hosts) == struct.unpack_from("<H", s, 0x38)[0], name      # all simple (1 model, 1 geometry)
        order, zone, over = draw_order(hosts)
        box = regions[name]
        land = land_area(s, hosts)
        clipped = []
        for grp, nm, parts in units:
            if grp == "zones":     # an opaque fill over water would look like land: fills stay on the land
                parts = [(sh.intersection(land) if layer == "zone_fill" else sh, layer) for sh, layer in parts]
            clipped.append((grp, nm, clip_pieces(parts, box)))
        stats = []
        for (grid, lab), plan in combos.items():
            take = {"zones", "borders"} | ({"lines", "ids"} if grid else set()) | ({"labels"} if lab else set())
            fills = [pc for grp, nm, pcs in clipped if grp in take for pc in pcs if pc["layer"] == "zone_fill"]
            rest = [pc for grp, nm, pcs in clipped if grp in take for pc in pcs if pc["layer"] != "zone_fill"]
            add = {}
            if fills and zone is not None:
                add.setdefault(zone["index"], []).extend(fills)
            if rest:
                add.setdefault(over["index"], []).extend(rest)
            for hi, pcs in add.items():
                h = hosts[[x["index"] for x in hosts].index(hi)]
                nv = h["n"] + sum(len(pc["v"]) for pc in pcs)
                ni = h["m"] + sum(3 * len(pc["t"]) for pc in pcs)
                if nv > MAX_V or ni > MAX_I:
                    raise RuntimeError("no room in %s drawable %d: %d verts %d indices" % (name, hi, nv, ni))
            if add:
                plan[name] = dict(order=order, hosts=[(hi, add[hi]) for hi in sorted(add, key=order.index)])
            stats.append("g%dl%d %d+%d" % (grid, lab, sum(len(pc["v"]) for pc in fills), sum(len(pc["v"]) for pc in rest)))
        print(name, "order", order, "zone host", zone["index"] if zone else None, "overlay host", over["index"], " ".join(stats))
    return combos


def land_area(s, hosts):
    """Union of the tile's vanilla land triangles (z 0)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    tris = []
    for h in hosts:
        if abs(h["z"]) < 0.5:
            v = np.frombuffer(bytes(s[h["vptr"]:h["vptr"] + 16 * h["n"]]), np.float32).reshape(-1, 4)[:, :2].astype(np.float64)
            idx = np.frombuffer(bytes(s[h["iptr"]:h["iptr"] + 2 * h["m"]]), np.uint16).reshape(-1, 3)
            tris += [Polygon(v[t]) for t in idx]
    return unary_union([t for t in tris if t.is_valid and t.area > 0]).buffer(0)


def drawable_info_indexed(s):
    """drawable_info() + the index of each drawable in the dictionary's pointer list."""
    out = []
    dp, dc = struct.unpack_from("<QH", s, 0x30)
    ptrs = [P(u64(s, P(dp) + 8 * i)) for i in range(dc)]
    for h in drawable_info(s):
        h["index"] = ptrs.index(h["d"])
        out.append(h)
    return out


# ------------------------------------------------------------------ page layout
PAGE_SIZES = [0x20000 >> k for k in range(5)]          # RSC7 system page classes 0..4: 128 KB .. 8 KB
PAGE_MAX = [1, 3, 15, 63, 127]
ROOT_SIZE = 0x40                                        # pgDictionary<rmcDrawable>
FLAG_SHIFT = [4, 5, 7, 11, 17]


class Relayout:
    """New blocks in new pages of the smallest class that fits; the pages are inserted after the
    vanilla pages of the same class (RSC7 keeps pages ordered by size), so the vanilla data
    behind them moves and every pointer into it is remapped. Pointers are found by scanning
    8-byte words for 0x5xxxxxxx values inside the segment, skipping the dictionary's name hash
    array (a hash + zero padding can look like a pointer; checked on all 65 vanilla tiles:
    9105 hits, all aligned, all structure pointers)."""

    def __init__(self, old_len, flags):
        assert flags & 0xF == 0 and (flags >> 24) & 0xF == 0, hex(flags)
        self.c = [(flags >> FLAG_SHIFT[k]) & PAGE_MAX[k] for k in range(5)]
        assert sum(self.c[k] * PAGE_SIZES[k] for k in range(5)) == old_len
        self.flags = flags
        self.data = [bytearray() for _ in range(5)]
        self.cur = [0] * 5
        self.blocks = []

    def pages(self):
        return sum(self.c) + sum(len(d) // PAGE_SIZES[k] for k, d in enumerate(self.data))

    @staticmethod
    def page_class(n):
        """Smallest page class that holds n bytes."""
        return max(k for k in range(5) if PAGE_SIZES[k] >= n)

    def first_class(self):
        return min(k for k in range(5) if self.c[k])

    def alloc(self, data, k=None):
        """Block id of `data` (never straddles a page, 16-byte aligned)."""
        n = len(data)
        if k is None:
            k = self.page_class(n)
        size = PAGE_SIZES[k]
        off = (self.cur[k] + 15) // 16 * 16
        if off % size + n > size:
            off = (off // size + 1) * size
        self.cur[k] = off + n
        need = (self.cur[k] + size - 1) // size * size
        d = self.data[k]
        if len(d) < need:
            d.extend(bytes(need - len(d)))
        d[off:off + n] = data
        self.blocks.append((k, off))
        return len(self.blocks) - 1

    def finalize(self, old, skip):
        """skip = (start, end) byte range that holds no pointers."""
        new = [len(self.data[k]) // PAGE_SIZES[k] for k in range(5)]
        for k in range(5):
            assert self.c[k] + new[k] <= PAGE_MAX[k], ("too many pages", k)
        self.os, self.ns, o, n = [], [], 0, 0
        for k in range(5):
            self.os.append(o)
            self.ns.append(n)
            o += self.c[k] * PAGE_SIZES[k]
            n += (self.c[k] + new[k]) * PAGE_SIZES[k]
        out = bytearray(n)
        for k in range(5):
            ln = self.c[k] * PAGE_SIZES[k]
            out[self.ns[k]:self.ns[k] + ln] = old[self.os[k]:self.os[k] + ln]
            out[self.ns[k] + ln:self.ns[k] + ln + len(self.data[k])] = self.data[k]
        w = np.frombuffer(bytes(old[:len(old) // 8 * 8]), np.uint64)
        pos = np.arange(len(w)) * 8
        hit = np.nonzero(((w >> np.uint64(32)) == 0) & ((w >> np.uint64(28)) == 5) &
                         ((w & np.uint64(0x0FFFFFFF)) < len(old)) & ((pos + 8 <= skip[0]) | (pos >= skip[1])))[0]
        for i in hit:
            struct.pack_into("<Q", out, self.remap(int(i) * 8), BASE + self.remap(int(w[i]) & 0x0FFFFFFF))
        f = self.flags
        for k in range(5):
            f = (f & ~(PAGE_MAX[k] << FLAG_SHIFT[k])) | ((self.c[k] + new[k]) << FLAG_SHIFT[k])
        return out, f

    def remap(self, o):
        for k in range(5):
            if self.os[k] <= o < self.os[k] + self.c[k] * PAGE_SIZES[k]:
                return o - self.os[k] + self.ns[k]
        raise ValueError(hex(o))

    def block(self, i):
        k, off = self.blocks[i]
        return self.ns[k] + self.c[k] * PAGE_SIZES[k] + off


# ------------------------------------------------------------------ apply (reference for the installer)
def apply_plan(path, tile_plan, theme_i, relief, land_lut, water_lut, colours):
    r = read_rsc(path)
    s = bytearray(r["sys"])
    # 1) recolour vanilla vertices through the theme LUTs
    for off, n, stride in vanilla_geometries(s):
        for v in range(n):
            o = off + v * stride
            z = struct.unpack_from("<f", s, o + 8)[0]
            lum = (s[o + 12] + s[o + 13] + s[o + 14]) // 3
            c = water_lut[lum] if z < 0 else land_lut[lum]
            s[o + 12], s[o + 13], s[o + 14] = int(c[0]), int(c[1]), int(c[2])
    if not tile_plan:
        return dict(sys=bytes(s), sysflags=r["sysflags"], gfxflags=r["gfxflags"], version=r["version"])
    hosts = {h["index"]: h for h in drawable_info_indexed(s)}
    order = tile_plan["order"]
    # 2) extended geometries as new blocks
    built = []
    for index, pieces in tile_plan["hosts"]:
        h = hosts[index]
        n, m = h["n"], h["m"]
        vdat = bytearray(s[h["vptr"]:h["vptr"] + n * 16])
        idx = list(struct.unpack_from("<%dH" % m, s, h["iptr"]))
        base = n
        for pc in pieces:
            z = LZ[pc["layer"]]
            c = colours[pc["layer"]]
            for x, y in pc["v"]:
                vdat += struct.pack("<fff", float(x), float(y), z) + bytes((int(c[0]), int(c[1]), int(c[2]), 255))
            idx += [base + i for t in pc["t"] for i in t]
            base += len(pc["v"])
        nv, ni = base, len(idx)
        assert nv <= MAX_V and ni <= MAX_I
        built.append((h, bytes(vdat), struct.pack("<%dH" % ni, *idx), nv, ni))
    R = Relayout(len(s), r["sysflags"])
    # the resource root must stay at offset 0, i.e. at the start of the first (largest) page:
    # when a new page is larger than every vanilla page, it gets a copy of the root struct
    k_new = min(R.page_class(len(b)) for _, vd, idd, _, _ in built for b in (vd, idd))
    root = R.alloc(bytes(ROOT_SIZE), k_new) if k_new < R.first_class() else None
    fix = []
    for h, vdat, idat, nv, ni in built:
        vv = np.frombuffer(vdat, np.float32).reshape(nv, 4)[:, :3].astype(np.float64)
        fix.append((h, R.alloc(vdat), R.alloc(idat), nv, ni, vv.min(axis=0), vv.max(axis=0)))
    b_models = R.alloc(bytes(8 * len(order)))
    pi_old = P(u64(s, 0x08))
    est = R.pages() + 1
    bp = R.alloc(bytes(16 + 8 * est))
    sys_pages = R.pages()
    assert sys_pages <= est
    hp, hc = P(u64(s, 0x20)), struct.unpack_from("<H", s, 0x28)[0]
    out, flags = R.finalize(s, (hp, hp + 4 * hc))
    if root is not None:
        assert R.block(root) == 0
        out[0:ROOT_SIZE] = out[R.remap(0):R.remap(0) + ROOT_SIZE]
    # 3) point the extended geometries at their new buffers (struct offsets moved with the relayout)
    ext = {}
    for h, bv, bi, nv, ni, mn, mx in fix:
        vb, ib, g, bnd = (R.remap(h[k]) for k in ("vb", "ib", "g", "bnd"))
        pv, pi = BASE + R.block(bv), BASE + R.block(bi)
        struct.pack_into("<Q", out, vb + 0x10, pv)
        struct.pack_into("<I", out, vb + 0x18, nv)
        struct.pack_into("<Q", out, vb + 0x20, pv)
        struct.pack_into("<I", out, ib + 0x08, ni)
        struct.pack_into("<Q", out, ib + 0x10, pi)
        struct.pack_into("<II", out, g + 0x58, ni, ni // 3)
        struct.pack_into("<H", out, g + 0x60, nv)
        struct.pack_into("<Q", out, g + 0x78, pv)
        struct.pack_into("<ffff", out, bnd, mn[0], mn[1], mn[2], mn[0])
        struct.pack_into("<ffff", out, bnd + 16, mx[0], mx[1], mx[2], mx[0])
        ext[h["index"]] = (mn, mx)
    # 4) all models of the tile in the last drawable of the order, the others keep none
    target = hosts[order[-1]]
    mn = np.array([np.inf] * 3); mx = np.array([-np.inf] * 3)
    for k, i in enumerate(order):
        h = hosts[i]
        mlist = P(u64(s, h["d"] + 0x50))
        model = P(u64(s, P(u64(s, mlist))))
        struct.pack_into("<Q", out, R.block(b_models) + 8 * k, BASE + R.remap(model))
        if i in ext:
            a, b = ext[i]
        else:
            vv = np.frombuffer(bytes(s[h["vptr"]:h["vptr"] + 16 * h["n"]]), np.float32).reshape(-1, 4)[:, :3].astype(np.float64)
            a, b = vv.min(axis=0), vv.max(axis=0)
        mn, mx = np.minimum(mn, a), np.maximum(mx, b)
    tl = R.remap(P(u64(s, target["d"] + 0x50)))
    struct.pack_into("<QHH", out, tl, BASE + R.block(b_models), len(order), len(order))
    d = R.remap(target["d"])
    c = (mn + mx) / 2
    struct.pack_into("<ffff", out, d + 0x20, c[0], c[1], c[2], float(np.linalg.norm(mx - mn) / 2))
    struct.pack_into("<fff", out, d + 0x30, *mn)
    struct.pack_into("<fff", out, d + 0x40, *mx)
    # the dictionary keeps the merged drawable and the sea ones (in their order: hashes stay sorted)
    dp, dc = P(u64(s, 0x30)), struct.unpack_from("<H", s, 0x38)[0]
    keep = [i for i in range(dc) if i == order[-1] or i not in order]
    for k, i in enumerate(keep):
        struct.pack_into("<I", out, R.remap(hp) + 4 * k, struct.unpack_from("<I", s, hp + 4 * i)[0])
        struct.pack_into("<Q", out, R.remap(dp) + 8 * k, BASE + R.remap(P(u64(s, dp + 8 * i))))
    struct.pack_into("<H", out, 0x28, len(keep))
    struct.pack_into("<H", out, 0x38, len(keep))
    # 5) pages info: relocated, one (runtime) slot per page
    o_pi = R.block(bp)
    out[o_pi:o_pi + 16] = s[pi_old:pi_old + 16]
    out[o_pi + 8] = sys_pages
    out[o_pi + 9] = 0
    struct.pack_into("<Q", out, 0x08, BASE + o_pi)
    return dict(sys=bytes(out), sysflags=flags, gfxflags=r["gfxflags"], version=r["version"])


# ------------------------------------------------------------------ binary export
def export(combos, path):
    from render import THEMES
    b = bytearray(b"NVPL")
    b += struct.pack("<IB", 4, len(LAYERS))
    for layer in LAYERS:
        b += struct.pack("<f", LZ[layer])
    b += struct.pack("<B", len(THEME_ORDER))
    for th in THEME_ORDER:
        T = THEMES[th]
        nb = th.encode("ascii")
        b += struct.pack("<B", len(nb)) + nb
        ll, wl = luts(T)
        b += ll.tobytes() + wl.tobytes()
        cols = layer_colours(T)
        for layer in LAYERS:
            b += bytes(cols[layer])
        for key in ("label", "label_stroke", "label_water", "grid", "grid_halo"):
            b += bytes(T[key])
    b += struct.pack("<B", len(combos))
    for (grid, lab), plan in sorted(combos.items()):
        b += struct.pack("<BBH", grid, lab, len(plan))
        for name, tp in sorted(plan.items()):
            nb = name.encode("ascii")
            b += struct.pack("<B", len(nb)) + nb
            b += struct.pack("<B", len(tp["order"])) + struct.pack("<%dH" % len(tp["order"]), *tp["order"])
            b += struct.pack("<H", len(tp["hosts"]))
            for index, pieces in tp["hosts"]:
                b += struct.pack("<HH", index, len(pieces))
                for pc in pieces:
                    nidx = len(pc["t"]) * 3
                    b += struct.pack("<BHH", LAYERS.index(pc["layer"]), len(pc["v"]), nidx)
                    b += np.asarray(pc["v"], np.float32).tobytes()
                    b += np.asarray([i for t in pc["t"] for i in t], np.uint16).tobytes()
    open(path, "wb").write(zlib.compress(bytes(b), 9))
    print("plan:", len(b), "bytes raw ->", os.path.getsize(path), "compressed")


def main():
    import shutil
    from render import THEMES
    combos = build_plan()
    export(combos, "build/vector_plan.bin")
    # expected outputs for the installer self-check (two variants)
    shutil.rmtree("build/vector_expected", ignore_errors=True)
    for th, grid, lab in (("dark", 0, 0), ("halloween", 1, 1)):
        T = THEMES[th]
        ll, wl = luts(T)
        out = "build/vector_expected/%s_%d_%d" % (th, grid, lab)
        os.makedirs(out, exist_ok=True)
        plan = combos[(grid, lab)]
        for p in sorted(glob.glob("files/game/minimap_ydd/minimap_*.ydd")):
            name = os.path.basename(p)
            res = apply_plan(p, plan.get(name, []), THEME_ORDER.index(th), False, ll, wl, layer_colours(T))
            open(os.path.join(out, name + ".sys"), "wb").write(res["sys"] + struct.pack("<I", res["sysflags"]))
        print("expected", out)


if __name__ == "__main__":
    main()
