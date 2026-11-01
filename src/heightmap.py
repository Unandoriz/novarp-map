"""GTA V heightmap.dat (HMAP, big-endian, row-compressed) reader + fit to the minimap raster."""
import struct
import json
import numpy as np


def load(path="files/game/heightmap.dat"):
    d = open(path, "rb").read()
    assert d[:4] == b"HMAP"
    vmaj, vmin, pad, comp, w, h = struct.unpack(">BBHIHH", d[4:16])
    bb = struct.unpack(">6f", d[16:40])
    length = struct.unpack(">I", d[40:44])[0]
    p = 44
    heads = []
    for _ in range(h):
        heads.append(struct.unpack(">HHi", d[p:p + 8]))
        p += 8
    data = d[p:]
    half = len(data) // 2
    mx = np.zeros((h, w), np.uint8)
    mn = np.zeros((h, w), np.uint8)
    for y, (start, count, off) in enumerate(heads):
        for i in range(count):
            x = start + i
            mx[y, x] = data[off + x]
            mn[y, x] = data[off + x + half]
    zmin, zmax = bb[2], bb[5]
    hmax = zmin + mx.astype(np.float32) / 255.0 * (zmax - zmin)
    hmin = zmin + mn.astype(np.float32) / 255.0 * (zmax - zmin)
    return dict(w=w, h=h, bbmin=bb[:3], bbmax=bb[3:], max=hmax, min=hmin, raw_max=mx)


if __name__ == "__main__":
    hm = load()
    print(hm["w"], hm["h"], hm["bbmin"], hm["bbmax"], hm["max"].max(), (hm["raw_max"] > 0).mean())
    # row 0 = which edge? print land fraction of first/last rows
    m = hm["raw_max"] > 0
    print("first rows land", m[:5].sum(axis=1), "last rows", m[-5:].sum(axis=1))
    from PIL import Image
    Image.fromarray(hm["raw_max"]).resize((hm["w"] * 3, hm["h"] * 3)).save("build/preview/heightmap_raw.png")
