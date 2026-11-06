"""Build map layers at 4096x6144 from the vanilla *vector* minimap tiles
(x64e.rpf/levels/gta5/minimap.rpf/minimap_X_Y.ydd, see minimap_mesh.py).

Meshes are rasterised 2x supersampled without per-triangle AA (avoids seams), then
downsampled. Writes build/layers.npz with float16 arrays:
  land    - land coverage (anti-aliased coastline)
  road    - road intensity (any road)
  major   - main roads / highways
  built   - buildings / urban structures (excluding roads)
  shallow - water shallowness 0 (deep) .. 1 (shore), from the sea depth bands
  ocean   - 1 where water is connected to the open sea
  height  - terrain height in metres (smoothed heightmap.dat), for the optional relief
"""
import glob
import numpy as np
import cv2
from scipy import ndimage
from heightmap import load as load_hm
from minimap_mesh import parse

UP = 2
W, H = 2048 * UP, 3072 * UP
X0, Y0, MPP = -4140.0, 8400.0, 9000.0 / (2048 * UP)   # world bounds of the minimap textures
SS = 2


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def rasterise():
    w, h = W * SS, H * SS
    scale = w / 9000.0
    lum = np.zeros((h, w), np.uint8)      # land detail (vanilla grey levels)
    land = np.zeros((h, w), np.uint8)
    sea = np.zeros((h, w), np.uint8)      # sea depth bands (vanilla blue-grey levels)
    geoms = []
    for p in sorted(glob.glob("files/game/minimap_ydd/minimap_*.ydd")):
        geoms += parse(p)
    order = sorted(range(len(geoms)), key=lambda i: (float(np.median(geoms[i]["pos"][:, 2])), i))
    for i in order:
        g = geoms[i]
        pos = g["pos"]
        pts = np.stack([(pos[:, 0] - X0) * scale, (Y0 - pos[:, 1]) * scale], 1)
        z = float(np.median(pos[:, 2]))
        tris = g["tris"]
        col = g["col"].astype(np.int32)
        tl = col[tris[:, 0], :3].mean(axis=1)          # flat colour per triangle
        for v in np.unique(tl):
            polys = list(np.round(pts[tris[tl == v]] * 16).astype(np.int32))
            if z < 0:
                cv2.fillPoly(sea, polys, int(v), cv2.LINE_8, 4)
            else:
                cv2.fillPoly(lum, polys, int(v), cv2.LINE_8, 4)
                cv2.fillPoly(land, polys, 255, cv2.LINE_8, 4)
    down = lambda a: cv2.resize(a.astype(np.float32), (W, H), interpolation=cv2.INTER_AREA)
    landf = down(land) / 255.0
    # average grey only over land samples (so the coastline doesn't darken the detail)
    lumf = down(lum) / np.maximum(landf, 1e-3)
    seaf = down(sea) / np.maximum(1 - landf, 1e-3)
    return landf, lumf, seaf


def main():
    landf, lum, sea = rasterise()
    # vanilla minimap palette: land 0x1d, buildings 0x20-0x41, roads 0x63+, main roads 0x96+
    road = smoothstep(80, 100, lum) * landf
    major = smoothstep(140, 152, lum) * landf
    built = np.maximum(smoothstep(30, 36, lum), smoothstep(26, 20, lum)) * (1 - road) * landf
    shallow = np.clip((sea - 85) / (220 - 85), 0, 1) * (1 - landf)

    water = landf < 0.5
    small = cv2.resize(water.astype(np.uint8), (W // 4, H // 4), interpolation=cv2.INTER_NEAREST)
    lab, n = ndimage.label(small)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    ocean = cv2.resize(np.isin(lab, list(border)).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)

    # heightmap -> raster space (only used by the relief variants)
    hm = load_hm()
    hgrid = np.flipud(hm["max"]).astype(np.float32)          # row 0 = north (Y = 8400)
    xs = X0 + (np.arange(W, dtype=np.float32) + 0.5) * MPP
    ys = Y0 - (np.arange(H, dtype=np.float32) + 0.5) * MPP
    col = (xs - hm["bbmin"][0]) / 50.0 - 0.5
    row = (hm["bbmax"][1] - ys) / 50.0 - 0.5
    mapx = np.broadcast_to(col[None, :], (H, W)).astype(np.float32)
    mapy = np.broadcast_to(row[:, None], (H, W)).astype(np.float32)
    F = 8
    hg = cv2.resize(hgrid, (hgrid.shape[1] * F, hgrid.shape[0] * F), interpolation=cv2.INTER_CUBIC)
    hg = cv2.GaussianBlur(hg, (0, 0), F * 0.6)
    height = cv2.remap(hg, mapx * F + (F - 1) / 2.0, mapy * F + (F - 1) / 2.0, cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    height = np.maximum(height, 0)

    np.savez_compressed("build/layers.npz",
                        land=landf.astype(np.float16), road=road.astype(np.float16), major=major.astype(np.float16),
                        built=built.astype(np.float16), shallow=shallow.astype(np.float16),
                        ocean=ocean.astype(np.float16), height=height.astype(np.float32))
    print("layers saved", W, H)


if __name__ == "__main__":
    main()
