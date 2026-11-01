"""Rebuild the vanilla vector minimap tiles (minimap_X_Y.ydd) for a theme:

  * every vanilla vertex colour is mapped to the theme palette (same classes as the
    raster map: water depth bands, land, buildings, roads, main roads);
  * hunting zones are merged into existing vanilla drawables (new drawables are not drawn
    by the game): a fill at z=3 (above land, below roads)
    and an outline at z=11.9 (just under the top road layer).

The host drawable's vertex and index data are moved into extra 8 KB system pages appended
after the vanilla ones (the smallest page class, so the vanilla pages keep their offsets) and
extended with the zone triangles; only buffer pointers, counts and bounds change in place.
"""
import glob
import json
import math
import os
import struct
import sys
import zlib
import numpy as np

from ytd import read_rsc
from layers import X0, Y0, MPP, smoothstep
import zones as zones_mod

BASE = 0x50000000
PAGE = 8192
FILL_Z, LINE_Z = 3.0, 11.9
LINE_W = 7.0          # outline width, metres
MAX_V, MAX_I = 512, 4096


def P(p):
    assert (p >> 28) == 5, hex(p)
    return p & 0x0FFFFFFF


def u64(b, o): return struct.unpack_from("<Q", b, o)[0]


# ---------------------------------------------------------------- theme colours
def theme_palette(T, land=None):
    """Map a vanilla vertex colour (r,g,b) + layer z to the theme colour."""
    land = tuple(land) if land is not None else T["land"]
    deep, shore = np.array(T["ocean_deep"], float), np.array(T["ocean_shore"], float)

    def f(r, g, b, z):
        lum = (r + g + b) / 3.0
        if z < 0:   # sea depth bands (blue-grey), light = shallow
            t = float(np.clip((lum - 85) / (220 - 85), 0, 1)) ** 1.3
            return tuple(int(round(v)) for v in deep + (shore - deep) * t)
        if lum >= 146:
            return T["major"]
        if lum >= 90:
            return T["road"]
        if 27 <= lum <= 31:
            return land
        return T["built"]
    return f


def zone_fill_colour(T):
    land, z = np.array(T["land"], float), np.array(T["zone_fill"], float)
    a = T["zone_fill_a"] * 1.1
    return tuple(int(round(v)) for v in land + (z - land) * a)


# ---------------------------------------------------------------- zone geometry (world space)
def px_to_world(p):
    p = np.asarray(p, float)
    return np.stack([X0 + p[:, 0] * MPP, Y0 - p[:, 1] * MPP], 1)


def ear_clip(poly):
    """Triangulate a simple polygon (list of 2D points). Returns index triples."""
    pts = np.asarray(poly, float)
    n = len(pts)
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]
    tris = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 100000:
        guard += 1
        m = len(idx)
        ear = False
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if cross(a, b, c) <= 1e-9:
                continue
            ok = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = pts[j]
                if cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0:
                    ok = False
                    break
            if ok:
                tris.append((i0, i1, i2))
                idx.pop(k)
                ear = True
                break
        if not ear:   # degenerate leftovers: fan
            break
    for k in range(1, len(idx) - 1):
        tris.append((idx[0], idx[k], idx[k + 1]))
    return tris


def ribbon(line, width, closed):
    """Quad strip of `width` centred on a polyline. Returns (verts2d, tris)."""
    L = np.asarray(line, float)
    if closed and np.allclose(L[0], L[-1]):
        L = L[:-1]
    n = len(L)
    nrm = np.zeros_like(L)
    for i in range(n):
        if closed:
            a, b = L[i - 1], L[(i + 1) % n]
        else:
            a, b = L[max(i - 1, 0)], L[min(i + 1, n - 1)]
        d = b - a
        d /= (np.linalg.norm(d) + 1e-9)
        nrm[i] = (-d[1], d[0])
    left, right = L + nrm * width / 2, L - nrm * width / 2
    verts = np.empty((2 * n, 2))
    verts[0::2], verts[1::2] = left, right
    tris = []
    segs = n if closed else n - 1
    for i in range(segs):
        j = (i + 1) % n
        a, b, c, d = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
        tris += [(a, b, c), (b, d, c)]
    return verts, tris


def rdp(pts, eps):
    """Ramer-Douglas-Peucker polyline simplification."""
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.linalg.norm(ab) + 1e-12
    d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.vstack([rdp(pts[:i + 1], eps)[:-1], rdp(pts[i:], eps)])
    return np.vstack([a, b])


def disc(c, r, seg=16):
    ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    v = np.vstack([c, np.stack([c[0] + r * np.cos(ang), c[1] + r * np.sin(ang)], 1)])
    return v, [(0, 1 + i, 1 + (i + 1) % seg) for i in range(seg)]


def zone_shapes():
    """[(shapely polygon in world coords, kind)] per zone, kind fill/line. Fills and outlines are
    proper polygons (buffers), so sharp bends of the strip zones don't fold over themselves."""
    from shapely.geometry import Polygon, LineString, LinearRing
    from shapely.ops import unary_union
    lw = LINE_W / 2

    def outline(shape):
        rings = []
        for p in getattr(shape, "geoms", [shape]):
            rings += [p.exterior] + list(p.interiors)
        return unary_union([LinearRing(r.coords).buffer(lw, quad_segs=3, join_style="round") for r in rings])

    out = []
    for z in zones_mod.build_zones():
        if z["kind"] == "poly":
            ring = px_to_world(zones_mod.catmull_rom_closed(z["points"], n_seg=8))
            shape = Polygon(ring).buffer(0)
        else:
            centre = px_to_world(rdp(z["centre"], 1.5))
            w = zones_mod.STRIP_W * MPP
            shape = LineString(centre).buffer(w / 2, quad_segs=8, cap_style="round", join_style="round")
        shape = shape.simplify(0.3, preserve_topology=True)
        out.append((shape, "fill"))
        out.append((outline(shape).simplify(0.3, preserve_topology=True), "line"))
    return out


def zone_meshes():
    """Returns list of (verts2d_world, tris, kind) for every zone, kind in fill/line."""
    import textgeo
    return [textgeo.triangulate(shape) + (kind,) for shape, kind in zone_shapes()]


def chunk(verts, tris, max_v=MAX_V, max_i=MAX_I):
    """Split a mesh into pieces with <= max_v vertices and <= max_i indices."""
    pieces, cur, remap = [], [], {}
    for t in tris:
        new = [i for i in t if i not in remap]
        if len(remap) + len(new) > max_v or (len(cur) + 1) * 3 > max_i:
            pieces.append((remap, cur))
            cur, remap = [], {}
        for i in t:
            if i not in remap:
                remap[i] = len(remap)
        cur.append(tuple(remap[i] for i in t))
    if cur:
        pieces.append((remap, cur))
    out = []
    for remap, ct in pieces:
        order = sorted(remap, key=remap.get)
        out.append((np.asarray(verts)[order], ct))
    return out


# ---------------------------------------------------------------- ydd patching
class Appender:
    """Appends blocks into new 8 KB pages after the original system segment."""

    def __init__(self, sys_len):
        assert sys_len % PAGE == 0
        self.base = sys_len
        self.data = bytearray()
        self.cur = 0

    @property
    def pages(self):
        return len(self.data) // PAGE

    def alloc(self, size, align=16):
        """Offset (relative to the appended area) for a block that never straddles a page."""
        assert size <= PAGE, size
        off = (self.cur + align - 1) // align * align
        if (off % PAGE) + size > PAGE:
            off = (off // PAGE + 1) * PAGE
        self.cur = off + size
        need = (self.cur + PAGE - 1) // PAGE * PAGE
        if len(self.data) < need:
            self.data.extend(b"\0" * (need - len(self.data)))
        return off

    def ptr(self, off):
        return BASE + self.base + off

    def put(self, off, b):
        self.data[off:off + len(b)] = b


def vanilla_geometries(s):
    """(vertex data offset, vertex count, stride, z) for every geometry of every drawable."""
    out = []
    hp, hc = struct.unpack_from("<QH", s, 0x20)
    dp, dc = struct.unpack_from("<QH", s, 0x30)
    for i in range(dc):
        d = P(u64(s, P(dp) + 8 * i))
        high = u64(s, d + 0x50)
        lp, lc = struct.unpack_from("<QH", s, P(high))
        for k in range(lc):
            m = P(u64(s, P(lp) + 8 * k))
            gp, gc = struct.unpack_from("<QH", s, m + 0x08)
            for j in range(gc):
                g = P(u64(s, P(gp) + 8 * j))
                vb = P(u64(s, g + 0x18))
                stride = struct.unpack_from("<H", s, vb + 0x08)[0]
                vdata, vcount = struct.unpack_from("<QI", s, vb + 0x10)
                out.append((P(vdata), vcount, stride))
    return out


def drawable_info(s):
    """Per vanilla drawable: offsets of its single geometry, buffers and counts."""
    out = []
    dp, dc = struct.unpack_from("<QH", s, 0x30)
    for i in range(dc):
        d = P(u64(s, P(dp) + 8 * i))
        mb = P(u64(s, d + 0x50))
        lp, lc = struct.unpack_from("<QH", s, mb)
        m = P(u64(s, P(lp)))
        gp, gc = struct.unpack_from("<QH", s, m + 0x08)
        if lc != 1 or gc != 1:
            continue
        g = P(u64(s, P(gp)))
        bnd = P(u64(s, m + 0x18))
        vb = P(u64(s, g + 0x18))
        ib = P(u64(s, g + 0x38))
        stride = struct.unpack_from("<H", s, vb + 0x08)[0]
        vptr, vcount = struct.unpack_from("<QI", s, vb + 0x10)
        icount = struct.unpack_from("<I", s, ib + 0x08)[0]
        iptr = u64(s, ib + 0x10)
        zs = [struct.unpack_from("<f", s, P(vptr) + k * stride + 8)[0] for k in range(vcount)]
        out.append(dict(d=d, g=g, bnd=bnd, vb=vb, ib=ib, stride=stride, vptr=P(vptr), n=vcount,
                        iptr=P(iptr), m=icount, z=float(np.median(zs))))
    return out


RELIEF_Z = 1.0
RELIEF_STEPS = (80.0, 110.0, 150.0, 200.0, 280.0)


def relief_context(theme):
    """Shading factor / tint maps identical to the raster relief (render.base), blurred to grid scale."""
    import cv2
    from render import terrain, THEMES
    from layers import smoothstep as ss
    T = THEMES[theme]
    L = dict(np.load("build/layers.npz"))
    h, shade = terrain(L)
    built = L["built"].astype(np.float32)
    road = L["road"].astype(np.float32)
    urban = cv2.GaussianBlur(np.clip(built + road, 0, 1), (0, 0), 30)
    st = T["shade_strength"] * (1 - ss(0.12, 0.4, urban) * 0.85)
    factor = np.clip(1 + (shade - 0.66) * st * 1.6, 0.74, 1.16)
    factor = cv2.GaussianBlur(factor.astype(np.float32), (0, 0), 12)
    tint = cv2.GaussianBlur(ss(5, 120, h).astype(np.float32), (0, 0), 12)
    flat = 1 + (np.sin(np.radians(45)) - 0.66) * T["shade_strength"] * 1.6
    low, hi = np.array(T["land_low"], np.float32), np.array(T["land"], np.float32)
    base = low * flat
    return dict(factor=factor, tint=tint, land=L["land"].astype(np.float32), low=low, hi=hi, base=base)


def relief_mesh(box, step, ctx):
    """Vertex-shaded grid over land cells whose shading differs from the flat base colour."""
    x0, y0, x1, y1 = box
    xs = np.arange(x0, x1 + step, step)
    ys = np.arange(y0, y1 + step, step)
    H_, W_ = ctx["land"].shape

    def px(x, y):
        return (min(max(int((x - X0) / MPP), 0), W_ - 1), min(max(int((Y0 - y) / MPP), 0), H_ - 1))

    def colour(x, y):
        c, r = px(x, y)
        t = ctx["tint"][r, c]
        return (ctx["low"] + (ctx["hi"] - ctx["low"]) * t) * ctx["factor"][r, c]

    cols = {}
    nodes = {}
    verts, tris, vcols = [], [], []

    def node(i, j):
        if (i, j) not in nodes:
            nodes[(i, j)] = len(verts)
            verts.append((xs[i], ys[j]))
            vcols.append(cols[(i, j)])
        return nodes[(i, j)]

    for i in range(len(xs)):
        for j in range(len(ys)):
            cols[(i, j)] = colour(xs[i], ys[j])
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            ca, cb = px(xs[i], ys[j + 1]), px(xs[i + 1], ys[j])     # top-left, bottom-right in pixels
            blk = ctx["land"][ca[1]:cb[1] + 1, ca[0]:cb[0] + 1]
            if blk.size == 0 or blk.min() < 0.99:
                continue
            corners = [cols[(i, j)], cols[(i + 1, j)], cols[(i, j + 1)], cols[(i + 1, j + 1)]]
            if max(np.abs(c - ctx["base"]).max() for c in corners) < 3.0:
                continue
            a, b, c, d = node(i, j), node(i + 1, j), node(i, j + 1), node(i + 1, j + 1)
            tris += [(a, b, d), (a, d, c)]
    return np.array(verts, float).reshape(-1, 2), tris, np.clip(np.array(vcols, float).reshape(-1, 3), 0, 255)


def pack(pieces, hosts):
    """Assign pieces to host drawables with spare capacity. Returns False if something did not fit
    (hosts are left untouched in that case)."""
    saved = [(h["av"], h["ai"], len(h["add"])) for h in hosts]
    for pc in sorted(pieces, key=lambda p: -len(p["v"])):
        # never host in the sea layer (z=-12): its triangles must stay under the land
        target_z, min_z = (12.0, 5.5) if pc["z"] > 6 else (0.0, -0.5)
        cands = sorted([h for h in hosts if h["z"] >= min_z], key=lambda h: (abs(h["z"] - target_z), h["n"] + h["av"]))
        cands += sorted([h for h in hosts if -0.5 <= h["z"] < min_z], key=lambda h: h["n"] + h["av"])
        for h in cands:
            if h["stride"] != 16:
                continue
            if h["n"] + h["av"] + len(pc["v"]) <= MAX_V and h["m"] + h["ai"] + 3 * len(pc["t"]) <= MAX_I:
                h["add"].append(pc)
                h["av"] += len(pc["v"])
                h["ai"] += 3 * len(pc["t"])
                break
        else:
            for h, (av, ai, na) in zip(hosts, saved):
                h["av"], h["ai"] = av, ai
                del h["add"][na:]
            return False
    return True


def patch_tile(path, meshes, T, tile_tag, relief=None):
    r = read_rsc(path)
    s = bytearray(r["sys"])
    pal = theme_palette(T, np.round(relief["base"]).astype(int) if relief else None)

    # 1) recolour vanilla vertices
    xs, ys = [], []
    for off, n, stride in vanilla_geometries(s):
        for v in range(n):
            o = off + v * stride
            x, y, z = struct.unpack_from("<fff", s, o)
            xs.append(x); ys.append(y)
            rr, g, b, a = s[o + 12:o + 16]   # vertex colour bytes are R, G, B, A
            nr, ng, nb = pal(rr, g, b, z)
            s[o + 12:o + 16] = bytes((nr, ng, nb, a))
    tile_box = (min(xs), min(ys), max(xs), max(ys))

    # 2) zone pieces overlapping this tile (small chunks so they pack into spare capacity)
    fill_col = np.array(zone_fill_colour(T), float)
    line_col = np.array(T["zone_line"], float)
    pieces = []
    for verts, tris, kind in meshes:
        bx = (verts[:, 0].min(), verts[:, 1].min(), verts[:, 0].max(), verts[:, 1].max())
        if bx[2] < tile_box[0] or bx[0] > tile_box[2] or bx[3] < tile_box[1] or bx[1] > tile_box[3]:
            continue
        col = fill_col if kind == "fill" else line_col
        for cv, ct in chunk(verts, tris, 96, 384):
            pieces.append(dict(v=cv, t=ct, z=FILL_Z if kind == "fill" else LINE_Z, c=np.tile(col, (len(cv), 1))))

    # 3) host drawables: fills / relief go into the land layer (z=0), outlines into the top layer
    #    (z=12). The game does not draw drawables that are not in the vanilla dictionary, so the
    #    geometry is appended to the vertex/index buffers of existing drawables.
    hosts = drawable_info(s)
    for h in hosts:
        h["add"] = []
        h["av"] = 0
        h["ai"] = 0
    if pieces and not pack(pieces, hosts):
        raise RuntimeError("no room for zone geometry in " + tile_tag)
    relief_step = None
    if relief:
        for step in RELIEF_STEPS:
            rv, rt, rc = relief_mesh(tile_box, step, relief)
            if not rt:
                break
            rp = []
            for cv, ct in chunk(np.column_stack([rv, rc]), rt, 96, 384):
                rp.append(dict(v=cv[:, :2], t=ct, z=RELIEF_Z, c=cv[:, 2:]))
            if pack(rp, hosts):
                pieces += rp
                relief_step = step
                break
    if not pieces:
        return dict(sys=bytes(s), sysflags=r["sysflags"], gfxflags=r["gfxflags"], version=r["version"], added=0)
    A = Appender(len(s))
    used = 0
    for h in hosts:
        if not h["add"]:
            continue
        used += 1
        n, m = h["n"], h["m"]
        vdat = bytearray(s[h["vptr"]:h["vptr"] + n * 16])
        idx = list(struct.unpack_from("<%dH" % m, s, h["iptr"]))
        allv = [np.frombuffer(bytes(vdat), np.float32).reshape(n, 4)[:, :3].astype(float)]
        base = n
        for pc in h["add"]:
            cv, ct, z = pc["v"], pc["t"], pc["z"]
            cc = np.clip(np.round(pc["c"]), 0, 255).astype(int)
            for (x, y), col in zip(cv, cc):
                vdat += struct.pack("<fff", float(x), float(y), z) + bytes((col[0], col[1], col[2], 255))
            idx += [base + i for t in ct for i in t]
            allv.append(np.column_stack([cv, np.full(len(cv), z)]))
            base += len(cv)
        nv, ni = base, len(idx)
        assert nv <= MAX_V and ni <= MAX_I and len(vdat) == nv * 16
        o_v = A.alloc(len(vdat))
        A.put(o_v, vdat)
        idat = struct.pack("<%dH" % ni, *idx)
        o_i = A.alloc(len(idat))
        A.put(o_i, idat)
        # vertex / index buffers (in place)
        struct.pack_into("<Q", s, h["vb"] + 0x10, A.ptr(o_v))
        struct.pack_into("<I", s, h["vb"] + 0x18, nv)
        struct.pack_into("<Q", s, h["vb"] + 0x20, A.ptr(o_v))
        struct.pack_into("<I", s, h["ib"] + 0x08, ni)
        struct.pack_into("<Q", s, h["ib"] + 0x10, A.ptr(o_i))
        # geometry counts (in place)
        g = h["g"]
        struct.pack_into("<II", s, g + 0x58, ni, ni // 3)
        struct.pack_into("<H", s, g + 0x60, nv)
        struct.pack_into("<Q", s, g + 0x78, A.ptr(o_v))
        # bounds: geometry AABB and drawable box / sphere
        pts = np.concatenate(allv)
        mn, mx = pts.min(axis=0), pts.max(axis=0)
        struct.pack_into("<ffff", s, h["bnd"], mn[0], mn[1], mn[2], mn[0])
        struct.pack_into("<ffff", s, h["bnd"] + 16, mx[0], mx[1], mx[2], mx[0])
        c = (mn + mx) / 2
        d = h["d"]
        struct.pack_into("<ffff", s, d + 0x20, c[0], c[1], c[2], float(np.linalg.norm(mx - mn) / 2))
        struct.pack_into("<fff", s, d + 0x30, *mn)
        struct.pack_into("<fff", s, d + 0x40, *mx)

    # 4) pages info (relocated: it lists one slot per page)
    pi_old = P(u64(s, 0x08))
    o_pi = A.alloc(16 + 8 * (s[pi_old + 8] + A.pages + 2))
    sys_pages = s[pi_old + 8] + A.pages
    pinfo = bytearray(16 + 8 * sys_pages)
    pinfo[0:16] = s[pi_old:pi_old + 16]
    pinfo[8] = sys_pages
    pinfo[9] = 0
    A.put(o_pi, pinfo)
    struct.pack_into("<Q", s, 0x08, A.ptr(o_pi))

    # 5) flags: original pages + A.pages more 8 KB pages (class s4 for ss=0)
    f = r["sysflags"]
    assert (f & 0xF) == 0, "unexpected page base"
    s4 = (f >> 17) & 0x7F
    assert s4 + A.pages <= 0x7F
    f = (f & ~(0x7F << 17)) | ((s4 + A.pages) << 17)
    return dict(sys=bytes(s) + bytes(A.data), sysflags=f, gfxflags=r["gfxflags"], version=r["version"],
                added=len(pieces), hosts=used, pages=A.pages, relief_step=relief_step)


def write_rsc(res, path):
    from ytd import rsc_size
    assert rsc_size(res["sysflags"]) == len(res["sys"]), (rsc_size(res["sysflags"]), len(res["sys"]))
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = comp.compress(res["sys"]) + comp.flush()
    open(path, "wb").write(struct.pack("<IIII", 0x37435352, res["version"], res["sysflags"], res["gfxflags"]) + body)


def main(variants):
    from render import THEMES
    meshes = zone_meshes()
    print("zone meshes:", len(meshes))
    for theme in variants:
        T = THEMES[theme.split("_")[0]]
        relief = relief_context(theme.split("_")[0]) if theme.endswith("_relief") else None
        out = "dist/vector/%s" % theme
        os.makedirs(out, exist_ok=True)
        tot = 0
        for p in sorted(glob.glob("files/game/minimap_ydd/minimap_*.ydd")):
            name = os.path.basename(p)
            res = patch_tile(p, meshes, T, name, relief)
            write_rsc(res, os.path.join(out, name))
            tot += res["added"]
            if res["added"]:
                print(theme, name, "pieces:", res["added"], "hosts:", res.get("hosts"), "pages:", res.get("pages"),
                      "relief step:", res.get("relief_step"))
        print(theme, "total zone pieces:", tot)


if __name__ == "__main__":
    main(sys.argv[1:] or ["dark", "light", "dark_relief", "light_relief"])
