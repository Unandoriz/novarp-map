"""Render the custom map for every variant (theme; the "_relief" variants are currently unused).

Base textures (build/map_<variant>.png, 4096 x 6144 RGBA): vector base, hunting zones,
city borders, legend. District / road names and the square grid are separate overlays
(build/overlay_labels.png, build/overlay_grid.png) that the installer composites on top
when the corresponding option is on; previews show them composited here the same way.
"""
import math
import sys
import numpy as np
import cv2
from PIL import Image

from layers import W, H, MPP, smoothstep
import zones as zones_mod
import labels as labels_mod

THEMES = {
    "dark": dict(
        ocean_deep=(11, 11, 12), ocean_shore=(62, 62, 65), ocean_cloud=(34, 34, 36),
        land=(112, 113, 116), land_low=(100, 101, 104), built=(88, 89, 92),
        road=(36, 36, 38), major=(15, 15, 16), shade_strength=0.5,
        zone_fill=(226, 70, 56), zone_fill_a=0.36, zone_line=(255, 96, 78), zone_glow=(255, 60, 40),
        label=(255, 255, 255), label_stroke=(14, 14, 15), label_water=(150, 152, 158),
        legend_bg=(22, 22, 24), legend_text=(235, 235, 235),
        border=(255, 196, 64), grid=(236, 236, 236), grid_halo=(14, 14, 15),
    ),
    "light": dict(
        ocean_deep=(146, 169, 186), ocean_shore=(214, 226, 233), ocean_cloud=(178, 196, 209),
        land=(236, 234, 228), land_low=(228, 225, 218), built=(212, 208, 200),
        road=(132, 134, 138), major=(62, 64, 68), shade_strength=0.4,
        zone_fill=(226, 64, 44), zone_fill_a=0.30, zone_line=(196, 40, 24), zone_glow=None,
        label=(32, 34, 38), label_stroke=(250, 250, 248), label_water=(70, 96, 118),
        legend_bg=(250, 250, 248), legend_text=(32, 34, 38),
        border=(36, 104, 196), grid=(40, 42, 46), grid_halo=(250, 250, 248),
    ),
    "winter": dict(
        ocean_deep=(32, 54, 80), ocean_shore=(160, 196, 224), ocean_cloud=(66, 96, 126),
        land=(240, 244, 249), land_low=(226, 233, 242), built=(204, 213, 226),
        road=(126, 144, 166), major=(56, 76, 102), shade_strength=0.45,
        zone_fill=(214, 56, 72), zone_fill_a=0.32, zone_line=(188, 30, 50), zone_glow=None,
        label=(28, 46, 70), label_stroke=(250, 252, 255), label_water=(40, 80, 120),
        legend_bg=(250, 252, 255), legend_text=(28, 46, 70),
        border=(36, 110, 196), grid=(34, 54, 84), grid_halo=(250, 252, 255),
    ),
    "halloween": dict(
        ocean_deep=(10, 6, 16), ocean_shore=(70, 40, 92), ocean_cloud=(34, 18, 48),
        land=(56, 46, 66), land_low=(48, 40, 58), built=(76, 62, 88),
        road=(126, 78, 28), major=(236, 128, 20), shade_strength=0.55,
        zone_fill=(120, 220, 60), zone_fill_a=0.34, zone_line=(160, 255, 90), zone_glow=(110, 255, 60),
        label=(255, 172, 64), label_stroke=(14, 8, 20), label_water=(176, 128, 208),
        legend_bg=(14, 8, 20), legend_text=(255, 200, 120),
        border=(196, 96, 255), grid=(255, 172, 64), grid_halo=(14, 8, 20),
    ),
}

VARIANTS = ["dark", "light", "winter", "halloween"]      # relief variants ("_relief") are off for now


def value_noise(scale, seed, h=H, w=W):
    rng = np.random.default_rng(seed)
    gh, gw = int(h / scale) + 4, int(w / scale) + 4
    g = rng.uniform(-1, 1, (gh, gw)).astype(np.float32)
    big = cv2.resize(g, (int(gw * scale), int(gh * scale)), interpolation=cv2.INTER_CUBIC)
    return big[int(scale):int(scale) + h, int(scale):int(scale) + w]


def fbm(scales, seed, ridged=False):
    acc = np.zeros((H, W), np.float32)
    amp, tot = 1.0, 0.0
    for i, s in enumerate(scales):
        n = value_noise(s, seed + i)
        if ridged:
            n = 1 - np.abs(n)
            n = n * n
        acc += n * amp
        tot += amp
        amp *= 0.55
    return acc / tot


def terrain(L):
    """Hillshade from heightmap.dat with light procedural ridges (0..1)."""
    h = L["height"].astype(np.float32)
    hills = smoothstep(15, 220, h)
    ridge = fbm([220, 110, 55, 27, 13], 11, ridged=True)
    hh = h * 1.3 + (ridge - 0.45) * 45.0 * hills
    gy, gx = np.gradient(hh, MPP)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect + math.pi / 2)
    return h, np.clip(shade, 0, 1)


def mix(a, b, t):
    return a + (b - a) * t[..., None]


def col(c):
    return np.array(c, np.float32)[None, None, :]


def base(theme, L, relief):
    T = THEMES[theme]
    land = L["land"].astype(np.float32)
    road = L["road"].astype(np.float32)
    major = L["major"].astype(np.float32)
    built = L["built"].astype(np.float32)
    shallow = L["shallow"].astype(np.float32)

    # water: depth bands from the vector map, soft clouds near the coast (like the reference map)
    clouds = np.clip(fbm([600, 300, 150, 75, 38], 101) * 0.5 + 0.5, 0, 1)
    sh = cv2.GaussianBlur(shallow, (0, 0), 3)
    water = mix(np.broadcast_to(col(T["ocean_deep"]), (H, W, 3)).copy(), col(T["ocean_cloud"]), np.clip(clouds * 0.3, 0, 1))
    water = mix(water, col(T["ocean_shore"]), np.clip(sh ** 1.3 * (0.6 + 0.8 * clouds), 0, 1))

    g = np.broadcast_to(col(T["land"]), (H, W, 3)).copy()
    if relief:
        h, shade = terrain(L)
        g = mix(col(T["land_low"]) + g * 0, col(T["land"]), smoothstep(5, 120, h))
        # cities stay flat: fade relief out where roads/buildings are dense
        urban = cv2.GaussianBlur(np.clip(built + road, 0, 1), (0, 0), 30)
        s = T["shade_strength"] * (1 - smoothstep(0.12, 0.4, urban) * 0.85)
        g = g * np.clip(1 + (shade - 0.66) * s * 1.6, 0.74, 1.16)[..., None]

    g = mix(g, col(T["built"]), built * 0.9)
    g = mix(g, col(T["road"]), road)
    g = mix(g, col(T["major"]), major)

    # open sea fades out like the vanilla texture (no hard map rectangle); lakes stay opaque
    va = np.array(Image.open("files/game/vanilla_sea_full.png"))[..., 3].astype(np.float32) / 255.0
    va = np.clip(cv2.resize(va, (W, H), interpolation=cv2.INTER_LINEAR) * 1.4, 0, 1)
    ocean = smoothstep(0.3, 0.7, L["ocean"].astype(np.float32))
    alpha = land + (1 - land) * (ocean * va + (1 - ocean))
    return np.clip(mix(water, g, land), 0, 255), alpha


def draw_borders(img, T):
    """Dashed city borders (land parts only), with a soft halo."""
    import json
    from PIL import ImageDraw
    a = np.array(img).astype(np.float32)
    m = Image.new("L", img.size, 0)
    hm = Image.new("L", img.size, 0)
    dm, dh = ImageDraw.Draw(m), ImageDraw.Draw(hm)
    dash, gap = 30.0, 18.0
    for pls in json.load(open("build/borders.json")).values():
        for pl in pls:
            pts = np.array(pl, float)
            seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            dist = np.concatenate([[0], np.cumsum(seg)])
            t = 0.0
            while t < dist[-1]:
                t1 = min(t + dash, dist[-1])
                xs = np.interp(np.linspace(t, t1, 6), dist, pts[:, 0])
                ys = np.interp(np.linspace(t, t1, 6), dist, pts[:, 1])
                q = list(zip(xs, ys))
                dh.line(q, fill=255, width=11)
                dm.line(q, fill=255, width=6)
                t += dash + gap
    m = np.asarray(m).astype(np.float32)[..., None] / 255
    hm = np.asarray(hm).astype(np.float32)[..., None] / 255
    a += (np.array(T["label_stroke"], np.float32) - a) * hm * 0.45
    a += (np.array(T["border"], np.float32) - a) * m
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB"), np.maximum(m[..., 0], hm[..., 0] * 0.7)


def composite(rgba, core, halo, core_col, halo_col, extra=None):
    """Same blend the installer uses: halo, then core colour; overlay pixels are opaque.
    rgba float32 HxWx4 (0..255); masks float 0..1; extra = (mask, colour) drawn last."""
    out = rgba.copy()
    for m, c in ((halo, halo_col), (core, core_col)) + ((extra,) if extra else ()):
        m3 = m[..., None]
        out[..., :3] += (np.array(c, np.float32) - out[..., :3]) * m3
        out[..., 3] = np.maximum(out[..., 3], m * 255)
    return out


def render(variant, debug_points=False):
    theme = variant.split("_")[0]
    T = THEMES[theme]
    L = dict(np.load("build/layers.npz"))
    rgb, alpha = base(theme, L, relief=variant.endswith("_relief"))
    img = Image.fromarray(rgb.astype(np.uint8), "RGB")
    img = zones_mod.draw(img, T, debug_points=debug_points)
    img, bmask = draw_borders(img, T)
    img = labels_mod.legend(img, T)
    # zones, borders and the legend are always opaque, also over the fading sea
    alpha = np.maximum.reduce([alpha, labels_mod.legend_mask(img.size), zones_mod.coverage(img.size), bmask])
    img = Image.fromarray(np.dstack([np.asarray(img), np.clip(alpha * 255, 0, 255).astype(np.uint8)]), "RGBA")
    img.save("build/map_%s.png" % variant)
    print("saved build/map_%s.png" % variant)
    return img


def overlays():
    """Theme-independent overlays: labels (R core, G halo, B water labels), grid (R core, G halo).
    The text geometry is also saved to build/text_geo.pkl for the vector tiles (vector_plan.py)."""
    import pickle
    import cv2
    import grid as grid_mod
    L = dict(np.load("build/layers.npz"))
    shapes = labels_mod.label_shapes(L["major"].astype(np.float32))
    core, halo, water = labels_mod.overlay_masks((W, H), shapes)
    Image.fromarray(np.dstack([core, halo, water]), "RGB").save("build/overlay_labels.png")
    busy = cv2.dilate((np.maximum.reduce([core, halo, water]) > 20).astype(np.uint8), np.ones((15, 15), np.uint8))
    ids = grid_mod.id_shapes(L["land"].astype(np.float32), busy)
    _, alpha = base("dark", L, relief=False)
    gc, gh = grid_mod.texture_masks(alpha, ids)
    g = np.dstack([gc, gh, np.zeros_like(gc)])
    Image.fromarray(np.clip(g * 255, 0, 255).astype(np.uint8), "RGB").save("build/overlay_grid.png")
    for name in ("labels", "grid"):
        im = Image.open("build/overlay_%s.png" % name)
        im.resize((1024, 1536), Image.LANCZOS).save("build/overlay_%s_small.png" % name)
    with open("build/text_geo.pkl", "wb") as f:
        pickle.dump(dict(labels=shapes, ids=ids), f)
    print("overlays saved:", len(shapes), "labels,", len(ids), "cell ids")


def preview(variant, labels=True, grid=False):
    """RGBA float composite of a variant with the optional overlays."""
    T = THEMES[variant.split("_")[0]]
    out = np.asarray(Image.open("build/map_%s.png" % variant).convert("RGBA")).astype(np.float32)
    if grid:
        g = np.asarray(Image.open("build/overlay_grid.png")).astype(np.float32) / 255
        out = composite(out, g[..., 0], g[..., 1], T["grid"], T["grid_halo"])
    if labels:
        o = np.asarray(Image.open("build/overlay_labels.png")).astype(np.float32) / 255
        out = composite(out, o[..., 0], o[..., 1], T["label"], T["label_stroke"], (o[..., 2], T["label_water"]))
    return out


if __name__ == "__main__":
    args = [t for t in sys.argv[1:] if not t.startswith("--")]
    if "--overlays" in sys.argv:
        overlays()
    for v in (args or ([] if "--overlays" in sys.argv else VARIANTS)):
        render(v, debug_points="--debug" in sys.argv)
