"""Theme previews for the installer window: build/installer/preview_<theme>_<labels><grid>.jpg.

300 x 450 composites of build/map_<theme>.png with the label / grid overlays (render.preview),
on the window background. The 1-2 px grid lines are thickened first so they survive the 13x
downscale.
"""
import os

import numpy as np
from PIL import Image, ImageFilter

import render

BG = np.array((34, 35, 38), np.float32)


def main():
    os.makedirs("build/installer", exist_ok=True)
    g = Image.open("build/overlay_grid.png")
    gc, gh = [ch.filter(ImageFilter.MaxFilter(k)) for ch, k in zip(g.split()[:2], (9, 17))]
    grid = np.dstack([np.asarray(gc), np.asarray(gh)]).astype(np.float32) / 255
    labels = np.asarray(Image.open("build/overlay_labels.png")).astype(np.float32) / 255
    for v in render.VARIANTS:
        T = render.THEMES[v.split("_")[0]]
        for lab in (0, 1):
            for gr in (0, 1):
                out = render.preview(v, labels=False, grid=False)
                if gr:
                    out = render.composite(out, grid[..., 0] * 0.75, grid[..., 1] * 0.6, T["grid"], T["grid_halo"])
                if lab:    # labels on top of the grid, as in the game
                    out = render.composite(out, labels[..., 0], labels[..., 1], T["label"], T["label_stroke"],
                                           (labels[..., 2], T["label_water"]))
                a = out[..., 3:4] / 255
                rgb = out[..., :3] * a + BG * (1 - a)
                im = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").resize((300, 450), Image.LANCZOS)
                im.save("build/installer/preview_%s_%d%d.jpg" % (v, lab, gr), quality=88)
        print(v)


if __name__ == "__main__":
    main()
