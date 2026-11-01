"""Painter's render of the expected vector tiles in draw order (no depth test).

    render_tiles.py variant out.png x0 y0 x1 y1 width        (world box: x0 y0 bottom-left, x1 y1 top-right)

All sea drawables of all tiles first (the lowest layer), then the merged drawables in their
model order; untouched vanilla tiles are approximated by height.
"""
import glob
import os
import struct
import sys

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
from ydd_zones import P, u64  # noqa: E402


def main():
    variant, out = sys.argv[1], sys.argv[2]
    x0, y0, x1, y1 = map(float, sys.argv[3:7])
    W = int(sys.argv[7])
    ss = 3
    sc = W * ss / (x1 - x0)
    H = int((y1 - y0) * sc)
    img = np.zeros((H, W * ss, 3), np.uint8)
    allg = []
    for ti, f in enumerate(sorted(glob.glob("build/vector_expected/%s/*.sys" % variant))):
        s = open(f, "rb").read()[:-4]
        dp, dc = struct.unpack_from("<QH", s, 0x30)
        geoms = []
        for i in range(dc):
            d = P(u64(s, P(dp) + 8 * i))
            ml = P(u64(s, d + 0x50))
            lp, lc = struct.unpack_from("<QH", s, ml)
            for k in range(lc):
                m = P(u64(s, P(lp) + 8 * k))
                g = P(u64(s, P(u64(s, m + 0x08))))
                vb, ib = P(u64(s, g + 0x18)), P(u64(s, g + 0x38))
                vptr, n = struct.unpack_from("<QI", s, vb + 0x10)
                mi = struct.unpack_from("<I", s, ib + 0x08)[0]
                v = np.frombuffer(s, np.uint8, n * 16, P(vptr)).reshape(n, 16)
                pos = v[:, :12].copy().view(np.float32).reshape(n, 3)
                idx = np.frombuffer(s, np.uint16, mi, P(u64(s, ib + 0x10))).reshape(-1, 3)
                geoms.append((lc > 1, pos, v[:, 12:15], idx))
        merged = any(g[0] for g in geoms)
        for li, g in enumerate(geoms):
            z = float(np.median(g[1][:, 2]))
            sea = (not g[0]) and z <= -0.5
            allg.append((0 if sea else 1, ti, li if merged else z, g))
    allg.sort(key=lambda e: e[:3])
    for _, _, _, (_, pos, col, idx) in allg:
        pts = np.round(np.stack([(pos[:, 0] - x0) * sc, (y1 - pos[:, 1]) * sc], 1) * 16).astype(np.int32)
        for t in idx:
            cv2.fillConvexPoly(img, pts[t], tuple(int(c) for c in col[t[0]]), cv2.LINE_8, 4)
    img = cv2.resize(img, (W, H // ss), interpolation=cv2.INTER_AREA)
    Image.fromarray(img).save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
