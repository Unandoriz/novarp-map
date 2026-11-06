"""Register the in-game map screenshots (zone/*.png) onto the vanilla minimap raster.

The screenshots are renders of the same raster (land/roads) as files/game/vanilla_sea_full.png,
so a multi-scale normalised cross-correlation finds scale + offset for each one.
Output: build/register.json  {name: {scale, x, y, score}}  where raster = x + px / scale.
"""
import json
import sys
import numpy as np
import cv2
from PIL import Image

BG = 25.0  # in-game colour under transparent sea


def raster_gray():
    a = np.array(Image.open("files/game/vanilla_sea_full.png")).astype(np.float32)
    al = a[..., 3:4] / 255.0
    rgb = a[..., :3] * al + BG * (1 - al)
    return rgb.mean(axis=2)


def shot(path):
    a = np.array(Image.open(path).convert("RGB")).astype(np.float32)
    gray = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    bad = (sat > 40) | (gray > 235)          # coloured blips, white pins
    bad = cv2.dilate(bad.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    return gray, bad


def match(rg, gray, bad, scales, region=None):
    best = (-2, None, None)
    x0 = y0 = 0
    sub = rg
    if region is not None:
        x0, y0, x1, y1 = region
        sub = rg[y0:y1, x0:x1]
    for s in scales:
        w = int(round(gray.shape[1] / s))
        h = int(round(gray.shape[0] / s))
        if w < 24 or h < 24 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        t = cv2.resize(gray, (w, h), interpolation=cv2.INTER_AREA)
        m = cv2.resize((~bad).astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
        m = (m > 0.95).astype(np.float32)
        res = cv2.matchTemplate(sub, t, cv2.TM_CCORR_NORMED, mask=m) if False else \
            cv2.matchTemplate(sub, t, cv2.TM_CCOEFF_NORMED, mask=m)
        res[~np.isfinite(res)] = -1
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, s, (loc[0] + x0, loc[1] + y0))
    return best


def main(names):
    rg = raster_gray()
    out = {}
    for n in names:
        gray, bad = shot("zone/%s.png" % n)
        coarse = np.exp(np.linspace(np.log(0.5), np.log(8.0), 90))
        sc, s, loc = match(rg, gray, bad, coarse)
        fine = s * np.exp(np.linspace(-0.04, 0.04, 33))
        w = gray.shape[1] / s
        h = gray.shape[0] / s
        pad = 40
        reg = (max(0, int(loc[0] - pad)), max(0, int(loc[1] - pad)),
               min(rg.shape[1], int(loc[0] + w * 1.1 + pad)), min(rg.shape[0], int(loc[1] + h * 1.1 + pad)))
        sc2, s2, loc2 = match(rg, gray, bad, fine, reg)
        if sc2 >= sc:
            sc, s, loc = sc2, s2, loc2
        out[n] = dict(scale=float(s), x=float(loc[0]), y=float(loc[1]), score=float(sc),
                      w=gray.shape[1], h=gray.shape[0])
        print(n, out[n], flush=True)
    json.dump(out, open("build/register.json", "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["global", "1", "2", "3", "4", "5", "road"])
