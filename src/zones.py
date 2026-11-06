"""Hunting zones: polygons through the user's pins + a strip that follows the road (road.png)."""
import json
import math
import numpy as np
import cv2
from PIL import Image
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from layers import W, H, UP, smoothstep

SS = 4  # cv2 sub-pixel shift bits
STRIP_W = 30  # road strip width, map px (4096 scale)


def catmull_rom_closed(pts, n_seg=24, alpha=0.5):
    """Centripetal Catmull-Rom through all points (closed curve)."""
    P = [np.array(p, np.float64) for p in pts]
    k = len(P)
    out = []
    for i in range(k):
        p0, p1, p2, p3 = P[(i - 1) % k], P[i], P[(i + 1) % k], P[(i + 2) % k]
        t0 = 0.0
        t1 = t0 + np.linalg.norm(p1 - p0) ** alpha
        t2 = t1 + np.linalg.norm(p2 - p1) ** alpha
        t3 = t2 + np.linalg.norm(p3 - p2) ** alpha
        for t in np.linspace(t1, t2, n_seg, endpoint=False):
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.array(out)


def order_ring(pts, interior=18.0 * UP):
    """Boundary ring in angular order. Points lying deep inside the convex hull
    (> `interior` px from its edge) are treated as interior marks, not boundary."""
    hull = cv2.convexHull(np.array(pts, np.float32))
    pts = [p for p in pts if cv2.pointPolygonTest(hull, (float(p[0]), float(p[1])), True) <= interior]
    c = np.mean(pts, axis=0)
    return sorted(pts, key=lambda p: math.atan2(p[1] - c[1], p[0] - c[0]))


def order_chain(pts, start):
    rest = list(pts)
    cur = min(rest, key=lambda p: (p[0] - start[0]) ** 2 + (p[1] - start[1]) ** 2)
    chain = [cur]
    rest.remove(cur)
    while rest:
        cur = min(rest, key=lambda p: (p[0] - chain[-1][0]) ** 2 + (p[1] - chain[-1][1]) ** 2)
        chain.append(cur)
        rest.remove(cur)
    return chain


def road_path(points, road, margin=40):
    """Follow the road network between consecutive points (Dijkstra on a road-cost grid)."""
    pts = np.array(points)
    x0 = int(max(0, pts[:, 0].min() - margin)); x1 = int(min(road.shape[1], pts[:, 0].max() + margin))
    y0 = int(max(0, pts[:, 1].min() - margin)); y1 = int(min(road.shape[0], pts[:, 1].max() + margin))
    sub = road[y0:y1, x0:x1].astype(np.float32)
    h, w = sub.shape
    cost = 1.0 + 60.0 * (1.0 - np.clip(sub, 0, 1)) ** 2
    idx = np.arange(h * w).reshape(h, w)
    rows, cols, vals = [], [], []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        ys, ys2 = slice(0, h - dy), slice(dy, h)
        if dx >= 0:
            xs, xs2 = slice(0, w - dx), slice(dx, w)
        else:
            xs, xs2 = slice(-dx, w), slice(0, w + dx)
        a = idx[ys, xs].ravel()
        b = idx[ys2, xs2].ravel()
        c = (cost[ys, xs].ravel() + cost[ys2, xs2].ravel()) * 0.5 * math.hypot(dx, dy)
        rows += [a, b]; cols += [b, a]; vals += [c, c]
    G = csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(h * w, h * w))
    path = []
    for a, b in zip(points[:-1], points[1:]):
        sa = idx[int(round(a[1])) - y0, int(round(a[0])) - x0]
        sb = idx[int(round(b[1])) - y0, int(round(b[0])) - x0]
        _, pred = dijkstra(G, indices=sa, return_predecessors=True)
        seg = []
        cur = sb
        while cur != sa and cur >= 0:
            seg.append(cur)
            cur = pred[cur]
        seg.append(sa)
        seg.reverse()
        if path:
            seg = seg[1:]
        path += [(n % w + x0, n // w + y0) for n in seg]
    p = np.array(path, np.float64)
    # smooth pixel staircase
    k = 9
    if len(p) > k:
        pad = np.concatenate([np.repeat(p[:1], k // 2, 0), p, np.repeat(p[-1:], k // 2, 0)])
        ker = np.ones(k) / k
        p = np.stack([np.convolve(pad[:, 0], ker, "valid"), np.convolve(pad[:, 1], ker, "valid")], 1)
        p[0], p[-1] = path[0], path[-1]
    return p


def build_zones():
    pins = json.load(open("build/pins.json"))
    zones = []
    for name in ["1", "2", "3", "4", "5"]:
        pts = [(x * UP, y * UP) for x, y in pins[name]["raster"]]
        ring = order_ring(pts)
        zones.append(dict(name=name, kind="poly", points=ring, outline=catmull_rom_closed(ring)))
    # road strip
    L = np.load("build/layers.npz")
    road = L["road"].astype(np.float32)
    rp = [(x * UP, y * UP) for x, y in pins["road"]["raster"]]
    z2 = np.mean([(x * UP, y * UP) for x, y in pins["2"]["raster"]], axis=0)
    chain = order_chain(rp, z2)
    centre = road_path(chain, road)
    zones.append(dict(name="road", kind="strip", points=chain, centre=centre))
    return zones


def zone_masks(z, width=STRIP_W):
    """Return (x0, y0, fill_mask) for a zone; masks are float 0..1 anti-aliased."""
    if z["kind"] == "poly":
        P = z["outline"]
    else:
        P = z["centre"]
    pad = width + 40
    x0 = int(P[:, 0].min() - pad); y0 = int(P[:, 1].min() - pad)
    x1 = int(P[:, 0].max() + pad); y1 = int(P[:, 1].max() + pad)
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    q = np.round((P - [x0, y0]) * (1 << SS)).astype(np.int32)
    if z["kind"] == "poly":
        cv2.fillPoly(m, [q], 255, cv2.LINE_AA, SS)
    else:
        cv2.polylines(m, [q], False, 255, width, cv2.LINE_AA, SS)
    return x0, y0, m.astype(np.float32) / 255.0


def ring(mask, lw):
    b = (mask > 0.5).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * lw + 1, 2 * lw + 1))
    r = cv2.dilate(b, k) - cv2.erode(b, k)
    return cv2.GaussianBlur(r.astype(np.float32), (0, 0), 0.8)


def draw(img, T, debug_points=False):
    a = np.array(img).astype(np.float32)
    zones = build_zones()
    json.dump([dict(name=z["name"], kind=z["kind"], points=[list(map(float, p)) for p in z["points"]])
               for z in zones], open("build/zones.json", "w"), indent=1)
    for z in zones:
        x0, y0, m = zone_masks(z)
        h, w = m.shape
        sub = a[y0:y0 + h, x0:x0 + w]
        fill = np.array(T["zone_fill"], np.float32)
        line = np.array(T["zone_line"], np.float32)
        lw = 3
        rg = ring(m, lw)
        if T.get("zone_glow"):
            gl = cv2.GaussianBlur(rg, (0, 0), 7) * 0.55
            sub += (np.array(T["zone_glow"], np.float32) - sub) * gl[..., None] * (1 - m[..., None] * 0.5)
        # hatch for texture, like the reference map's striped zone
        yy, xx = np.mgrid[0:h, 0:w]
        hatch = (((xx + yy + x0 + y0) // 9) % 2).astype(np.float32)
        fa = T["zone_fill_a"] * (0.82 + 0.18 * hatch)
        sub += (fill - sub) * (m * fa)[..., None]
        sub += (line - sub) * np.clip(rg, 0, 1)[..., None]
        a[y0:y0 + h, x0:x0 + w] = np.clip(sub, 0, 255)
    out = Image.fromarray(a.astype(np.uint8), "RGB")
    if debug_points:
        from PIL import ImageDraw
        d = ImageDraw.Draw(out)
        for z in zones:
            for x, y in z["points"]:
                d.ellipse((x - 5, y - 5, x + 5, y + 5), outline=(0, 255, 255), width=2)
    return out


def coverage(size):
    """Opacity mask (0..1) of all zones incl. outline/glow, used for the texture alpha."""
    W_, H_ = size
    cov = np.zeros((H_, W_), np.float32)
    for z in build_zones():
        x0, y0, m = zone_masks(z)
        h, w = m.shape
        rg = cv2.GaussianBlur(ring(m, 3), (0, 0), 4)
        cov[y0:y0 + h, x0:x0 + w] = np.maximum(cov[y0:y0 + h, x0:x0 + w], np.clip(m + rg * 2, 0, 1))
    return cov
