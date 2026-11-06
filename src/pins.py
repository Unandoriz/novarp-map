"""Find the white map pins in zone screenshots and convert their tips to raster coordinates."""
import json
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

reg = json.load(open("build/register.json"))

# Pins the detector can't see, measured by hand (screen px of the screenshot, pin tip):
#  zone 1: pin hidden under the wolf blip, pin under the mouse cursor,
#          and the user's red marker (they ran out of white pins for this zone).
MANUAL = {"1": [(326.3, 230.5), (386.3, 129.5), (473.8, 221.3)]}


def find_pins(path):
    a = np.array(Image.open(path).convert("RGB")).astype(np.float32)
    g = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    dark = (g < 14) & (sat < 20)
    lab, n = ndimage.label(dark)
    pins = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        comp = lab[sl] == i
        area = comp.sum()
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (120 < area < 700 and 12 <= w <= 32 and 18 <= h <= 44 and h > w):
            continue
        ys, xs = np.nonzero(comp)
        bottom = ys.max()
        tipx = xs[ys >= bottom - 2].mean() + sl[1].start
        tipy = bottom + sl[0].start + 2.5
        # a white dot must sit inside the upper part of the body
        top = sl[0].start
        sub = g[top:top + h // 2 + 2, sl[1]]
        if (sub > 200).sum() < 15:
            continue
        pins.append((float(tipx), float(tipy)))
    return pins


def to_raster(name, pts):
    r = reg[name]
    return [(r["x"] + px / r["scale"], r["y"] + py / r["scale"]) for px, py in pts]


if __name__ == "__main__":
    out = {}
    for n in ["1", "2", "3", "4", "5", "road"]:
        p = find_pins("zone/%s.png" % n) + list(MANUAL.get(n, []))
        out[n] = dict(screen=p, raster=to_raster(n, p))
        print(n, len(p), [(round(x), round(y)) for x, y in p])
        # debug overlay on the screenshot
        im = Image.open("zone/%s.png" % n).convert("RGB")
        d = ImageDraw.Draw(im)
        for x, y in p:
            d.ellipse((x - 3, y - 3, x + 3, y + 3), outline=(255, 0, 0), width=2)
        im.save("build/preview/pins_%s.png" % n)
    json.dump(out, open("build/pins.json", "w"), indent=1)
