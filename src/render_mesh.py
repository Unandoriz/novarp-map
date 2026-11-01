"""Rasterise all vanilla vector minimap tiles into one image (world -> map pixels).

Output: build/mesh_<scale>.png (RGBA, colours as stored in the meshes) and
build/mesh_layers.npz with per-colour coverage masks used by the themed renderer.
"""
import glob
import os
import sys
import numpy as np
import cv2
from minimap_mesh import parse

X0, Y0, MAPW = -4140.0, 8400.0, 9000.0   # world bounds of the minimap textures (2 x 3 tiles of 4500 m)


def load_all():
    geoms = []
    for p in sorted(glob.glob("files/game/minimap_ydd/*.ydd")):
        for g in parse(p):
            g["file"] = os.path.basename(p)
            geoms.append(g)
    return geoms


def render(W, geoms, ss=4):
    H = W * 3 // 2
    scale = W / MAPW
    img = np.zeros((H, W, 4), np.uint8)
    shift = ss
    # depth order per triangle (the game layers by z: sea -12, land 0, features 6..12)
    layers = {}
    for g in geoms:
        pos = g["pos"]
        pts = np.stack([(pos[:, 0] - X0) * scale, (Y0 - pos[:, 1]) * scale], 1)
        tz = pos[g["tris"][:, 0], 2]
        tc = g["col"][g["tris"][:, 0]].view(np.uint32).ravel()
        for z in np.unique(tz):
            for c in np.unique(tc[tz == z]):
                sel = g["tris"][(tz == z) & (tc == c)]
                layers.setdefault(float(z), []).append((c, np.round(pts[sel] * (1 << shift)).astype(np.int32)))
    for z in sorted(layers):
        for c, polys in layers[z]:
            r, gg, b, a = [int(v) for v in np.array([c], np.uint32).view(np.uint8)]   # R, G, B, A bytes
            cv2.fillPoly(img, list(polys), (r, gg, b, 255), cv2.LINE_AA, shift)
    return img


if __name__ == "__main__":
    W = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
    geoms = load_all()
    print(len(geoms), "geometries")
    allp = np.concatenate([g["pos"] for g in geoms])
    print("world bounds x %.0f..%.0f y %.0f..%.0f" % (allp[:, 0].min(), allp[:, 0].max(), allp[:, 1].min(), allp[:, 1].max()))
    cols = np.unique(np.concatenate([g["col"].view(np.uint32).ravel() for g in geoms]))
    print("colours:", [hex(c) for c in cols])
    zs = {}
    for g in geoms:
        z = float(np.median(g["pos"][:, 2]))
        for c in np.unique(g["col"].view(np.uint32)):
            zs.setdefault(hex(c), set()).add(z)
    print("colour -> z:", {k: sorted(v) for k, v in zs.items()})
    img = render(W, geoms)
    from PIL import Image
    Image.fromarray(img, "RGBA").save("build/mesh_%d.png" % W)
    print("saved build/mesh_%d.png" % W)
