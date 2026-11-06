"""Cherry-blossom decor of the "sakura" theme: scalloped patches on the land and a pale scalloped
rim along the sea coast, as polygons (map px, y down).

The texture rasterises these polygons and the vector tiles triangulate the same ones, so the map
looks the same at every zoom level (decor on the texture only would be covered by the flat
vector land when zoomed in). Zones are cut out: their vector fill is opaque, the texture one is
not, and without decor under them both look alike.
"""
import os
import pickle

import cv2
import numpy as np
from shapely import affinity
from shapely.geometry import Point
from shapely.ops import unary_union

from layers import W, H, X0, Y0, MPP
import textgeo

CACHE = "build/sakura_geo.pkl"
COVER, COVER_DEEP = 0.30, 0.11       # share of the open land under the patches / their dark cores
RIM_MIN_AREA = 40000                 # px^2


def _discs(points, rng, rmin, rmax):
    return unary_union([Point(float(x), float(y)).buffer(float(r), quad_segs=3)
                        for (x, y), r in zip(points, rng.uniform(rmin, rmax, len(points)))])


def _scatter(mask, spacing, rng):
    """Jittered grid points inside the mask."""
    gx, gy = np.meshgrid(np.arange(0, W, spacing, dtype=np.float32), np.arange(0, H, spacing, dtype=np.float32))
    pts = np.stack([gx.ravel(), gy.ravel()], 1) + rng.uniform(-0.4, 0.4, (gx.size, 2)) * spacing
    pts = pts[(pts[:, 0] >= 0) & (pts[:, 0] < W) & (pts[:, 1] >= 0) & (pts[:, 1] < H)]
    return pts[mask[pts[:, 1].astype(int), pts[:, 0].astype(int)]]


def _coast_points(land, ocean, spacing):
    """One point per grid cell of the land's edge along the open sea."""
    lb = land > 0.5
    sea = ((ocean > 0.5) & ~lb).astype(np.uint8)
    ys, xs = np.nonzero(lb & (cv2.dilate(sea, np.ones((5, 5), np.uint8)) > 0))
    _, first = np.unique((ys // spacing) * (W // spacing + 1) + xs // spacing, return_index=True)
    return np.stack([xs[first], ys[first]], 1).astype(np.float32)


def build():
    from render import fbm
    from ydd_zones import zone_shapes
    L = dict(np.load("build/layers.npz"))
    land, ocean = L["land"].astype(np.float32), L["ocean"].astype(np.float32)
    urban = cv2.GaussianBlur(np.clip(L["built"].astype(np.float32) + L["road"].astype(np.float32), 0, 1), (0, 0), 24)
    open_land = (land > 0.95) & (urban < 0.10)
    n = fbm([170, 85, 42], 707)
    rng = np.random.default_rng(1707)
    blossom = _discs(_scatter(open_land & (n > np.quantile(n[open_land], 1 - COVER)), 30, rng), rng, 20, 34)
    deep = _discs(_scatter(open_land & (n > np.quantile(n[open_land], 1 - COVER_DEEP)), 24, rng), rng, 12, 22)
    rim = _discs(_coast_points(land, ocean, 28), rng, 18, 30)
    # islets would float in the sea as separate bubbles: only the rim of the big coasts stays
    rim = unary_union([p for p in rim.geoms if p.area >= RIM_MIN_AREA])
    k = 1 / MPP
    zones = unary_union([affinity.affine_transform(sh, [k, 0, 0, -k, -X0 * k, Y0 * k]) for sh, kind in zone_shapes() if kind == "fill"])
    geo = {name: sh.difference(zones).simplify(0.8, preserve_topology=True)
           for name, sh in (("rim", rim), ("blossom", blossom), ("blossom_deep", deep))}
    with open(CACHE, "wb") as f:
        pickle.dump(geo, f)
    return geo


def shapes():
    """{"rim", "blossom", "blossom_deep": (multi)polygon in map px}."""
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    return build()


def mask(shape):
    """Coverage 0..1 of a (multi)polygon at map resolution."""
    return textgeo.rasterize(list(getattr(shape, "geoms", [shape])), (W, H), ss=2).astype(np.float32) / 255
