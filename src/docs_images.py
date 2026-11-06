"""Pictures for the repository's README: docs/images/{themes,options,zoom}.jpg, installer.png.

Run from the project root after render.py, vector_plan.py and the installer test (it refreshes
build/preview/installer_ui.png). All of them are renders of the map, not in-game screenshots.
"""
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

import render
from labels import font
from layers import X0, Y0, MPP

OUT = "docs/images"
BG = (22, 23, 26)
NAMES = (("dark", "Тёмная"), ("light", "Светлая"), ("winter", "Зима"), ("halloween", "Хэллоуин"), ("sakura", "Сакура"))


def flat(out, bg=BG):
    a = out[..., 3:4] / 255
    return Image.fromarray(np.clip(out[..., :3] * a + np.array(bg, np.float32) * (1 - a), 0, 255).astype(np.uint8), "RGB")


def caption(d, xy, text, size=30, fill=(236, 236, 240)):
    f = font(size, "SemiBold")
    d.text((xy[0] - d.textlength(text, font=f) / 2, xy[1]), text, font=f, fill=fill)


def themes():
    """All themes side by side."""
    box = (150, 250, 3950, 5950)           # the island and its coast, without the legend
    w, h, gap, pad, cap = 360, 540, 12, 24, 62
    img = Image.new("RGB", (pad * 2 + 5 * w + 4 * gap, pad + h + cap), BG)
    d = ImageDraw.Draw(img)
    for i, (theme, name) in enumerate(NAMES):
        x = pad + i * (w + gap)
        img.paste(flat(render.preview(theme, labels=True, grid=False)).crop(box).resize((w, h), Image.LANCZOS), (x, pad))
        caption(d, (x + w / 2, pad + h + 12), name)
    img.save(OUT + "/themes.jpg", quality=88)


def options():
    """The same spot without and with the optional overlays."""
    box = (1560, 3560, 2760, 4560)
    w, h, gap, pad, cap = 600, 500, 12, 24, 62
    states = (("Чистая", False, False), ("Подписи районов и дорог", True, False), ("Подписи и сетка", True, True))
    img = Image.new("RGB", (pad * 2 + 3 * w + 2 * gap, pad + h + cap), BG)
    d = ImageDraw.Draw(img)
    for i, (name, labels, grid) in enumerate(states):
        x = pad + i * (w + gap)
        img.paste(flat(render.preview("dark", labels=labels, grid=grid)).crop(box).resize((w, h), Image.LANCZOS), (x, pad))
        caption(d, (x + w / 2, pad + h + 12), name)
    img.save(OUT + "/options.jpg", quality=88)


def zoom():
    """Far view (texture) and close view (vector tiles) of the same spot."""
    px = (1500, 1700, 2900, 2700)
    world = (X0 + px[0] * MPP, Y0 - px[3] * MPP, X0 + px[2] * MPP, Y0 - px[1] * MPP)
    tmp = "build/preview/docs_vector.png"
    subprocess.check_call([sys.executable, "src/checks/render_tiles.py", "sakura_1_1", tmp] + ["%.1f" % v for v in world] + ["900"])
    vec = Image.open(tmp).convert("RGB")
    tex = flat(render.preview("sakura", labels=True, grid=True)).crop(px).resize(vec.size, Image.LANCZOS)
    gap, pad, cap = 12, 24, 62
    img = Image.new("RGB", (pad * 2 + vec.width * 2 + gap, pad + vec.height + cap), BG)
    d = ImageDraw.Draw(img)
    for i, (pic, name) in enumerate(((tex, "Издалека"), (vec, "В приближении и на радаре"))):
        x = pad + i * (vec.width + gap)
        img.paste(pic, (x, pad))
        caption(d, (x + vec.width / 2, pad + vec.height + 12), name)
    img.save(OUT + "/zoom.jpg", quality=88)


def main():
    os.makedirs(OUT, exist_ok=True)
    themes()
    options()
    zoom()
    shutil.copy("build/preview/installer_ui.png", OUT + "/installer.png")
    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")


if __name__ == "__main__":
    main()
