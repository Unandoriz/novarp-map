"""Labels (Russian): district names, road names, the legend.

District and road names are not baked into the base textures: they go into an overlay
(core / halo / water masks) that the installer composites on top when "Подписи" is on, and
into the vector tiles as triangles of the very same glyph outlines (textgeo.py).
The legend (zones + city border) is always part of the base map.
"""
import math
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/bahnschrift.ttf"

# (text, x, y, kind)  kind: "big" | "town" | "small" | "water"
LABELS = [
    ("ГОРА\nЧИЛИАД", 2089, 1300, "big"),
    ("ПАЛЕТО-БЕЙ", 1600, 760, "town"),
    ("ЛЕС ПАЛЕТО", 1611, 1380, "small"),
    ("ГРЕЙПСИД", 2810, 1420, "town"),
    ("ГОРА ГОРДО", 3204, 1320, "small"),
    ("СЕНДИ-ШОРС", 2730, 1950, "town"),
    ("АЛАМО-СИ", 2420, 2040, "water"),
    ("ХУМАНКА", 3523, 2080, "small"),
    ("АЭРОПОРТ-СШ", 2500, 2500, "small"),
    ("ФЕДЕРАЛЬНАЯ\nТЮРЬМА", 2600, 2700, "small"),
    ("ПУСТЫНЯ\nГРАНД-СЕНОРА", 2960, 2420, "small"),
    ("КАРЬЕР", 3227, 2640, "small"),
    ("ВЕТРЯКИ", 2900, 2980, "small"),
    ("ХАРМОНИ", 2158, 2560, "small"),
    ("ГРЕЙТ-ЧАПАРРАЛ", 1702, 2840, "small"),
    ("ФОРТ-ЗАНКУДО", 850, 2400, "town"),
    ("ЧУМАШ", 560, 3250, "small"),
    ("ПАСИФИК-БЛАФФС", 974, 3641, "small"),
    ("ВАЙНВУД-ХИЛЛЗ", 1720, 3400, "small"),
    ("ВАЙНВУД", 2040, 3720, "town"),
    ("РОКФОРД-ХИЛЛЗ", 1500, 3880, "small"),
    ("ДЕЛЬ-ПЕРРО", 1120, 4150, "small"),
    ("ВЕСПУЧЧИ", 1300, 4500, "small"),
    ("ДАУНТАУН", 1940, 4190, "small"),
    ("МИРРОР-ПАРК", 2420, 3990, "small"),
    ("ЛА-МЕСА", 2250, 4330, "small"),
    ("ДЭВИС", 1930, 4600, "small"),
    ("ГОРЫ ТАТАВИАМ", 2800, 3820, "small"),
    ("АЭРОПОРТ-ЛС", 1290, 5150, "town"),
    ("ПОРТ", 2350, 5440, "town"),
]

# Road names (RU game localisation transliterates street names: "Альта-стрит" etc.).
# (text, x, y, side): approximate anchor in map px; it is snapped to the nearest main road
# and the text is turned along it, offset to one side of the road (side = +1 / -1).
ROAD_LABELS = [
    ("ГРЕЙТ-ОУШЕН-ХАЙВЕЙ", 1200, 1560, 1),
    ("ГРЕЙТ-ОУШЕН-ХАЙВЕЙ", 760, 2050, 1),
    ("ГРЕЙТ-ОУШЕН-ХАЙВЕЙ", 2330, 860, -1),
    ("СЕНОРА-ФРИВЕЙ", 3160, 1250, 1),
    ("СЕНОРА-ФРИВЕЙ", 3110, 2150, 1),
    ("ШОССЕ 68", 1300, 2705, -1),
    ("ЛОС-САНТОС-ФРИВЕЙ", 2900, 3520, 1),
    ("ДЕЛЬ-ПЕРРО-ФРИВЕЙ", 1600, 4058, -1),
    ("ЛА-ПУЭРТА-ФРИВЕЙ", 1640, 4620, 1),
    ("ПАЛОМИНО-ФРИВЕЙ", 2800, 4150, 1),
]


def font(size, style):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_name(style)
    return f


def draw_text(d, xy, text, f, fill, stroke, sw, tracking=0.08, anchor_center=True):
    lines = text.split("\n")
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * 0.92)
    widths = []
    for ln in lines:
        wsum = 0
        for ch in ln:
            wsum += f.getlength(ch) + f.size * tracking
        widths.append(wsum - f.size * tracking)
    x, y = xy
    y -= lh * len(lines) / 2
    for ln, wl in zip(lines, widths):
        cx = x - wl / 2 if anchor_center else x
        for ch in ln:
            d.text((cx, y), ch, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke)
            cx += f.getlength(ch) + f.size * tracking
        y += lh


STYLE = {
    "big": (74, "Bold", 6),
    "town": (52, "Bold", 5),
    "small": (36, "SemiBold", 4),
    "water": (44, "SemiBold SemiCondensed", 0),
}
ROAD_STYLE = (30, "SemiBold SemiCondensed", 4)


# ------------------------------------------------------------------ legend (always on)
def legend(img, T, x0=3260, y0=5700, mask=None):
    """Legend without a panel: zone swatch + dashed city border, captions with a halo.
    With mask (an "L" image) draws the opaque coverage instead, for the texture alpha."""
    rows = [("zone", "зоны охоты"), ("border", "граница города")]
    f = font(44, "SemiBold")
    if mask is not None:
        d = ImageDraw.Draw(mask)
        for i, (kind, text) in enumerate(rows):
            y = y0 + i * 96
            d.rounded_rectangle((x0 - 4, y - 4, x0 + 100, y + 70), radius=18, fill=255)
            draw_text(d, (x0 + 128, y + 33), text, f, 255, 255, 5, tracking=0.04, anchor_center=False)
        return mask
    base = img.convert("RGBA")
    for i, (kind, text) in enumerate(rows):
        y = y0 + i * 96
        sx0, sy0, sx1, sy1 = x0, y, x0 + 96, y + 66
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        if kind == "zone":
            fa = int(255 * T["zone_fill_a"] * 1.6)
            hatch = Image.new("RGBA", img.size, (0, 0, 0, 0))
            hd = ImageDraw.Draw(hatch)
            hd.rounded_rectangle((sx0, sy0, sx1, sy1), radius=16, fill=T["legend_bg"] + (255,))
            hd.rounded_rectangle((sx0, sy0, sx1, sy1), radius=16, fill=T["zone_fill"] + (fa,))
            for k in range(-120, 120, 14):
                hd.line((sx0 + k, sy1, sx0 + k + (sy1 - sy0), sy0), fill=T["zone_fill"] + (min(255, fa + 40),), width=5)
            m = Image.new("L", img.size, 0)
            ImageDraw.Draw(m).rounded_rectangle((sx0, sy0, sx1, sy1), radius=16, fill=255)
            ov.paste(hatch, (0, 0), m)
            od.rounded_rectangle((sx0, sy0, sx1, sy1), radius=16, outline=T["zone_line"] + (255,), width=5)
        else:
            od.rounded_rectangle((sx0, sy0, sx1, sy1), radius=16, fill=T["legend_bg"] + (255,))
            cy = (sy0 + sy1) // 2
            for xx in range(sx0 + 10, sx1 - 10, 30):
                od.line((xx, cy, min(xx + 18, sx1 - 10), cy), fill=T["border"] + (255,), width=7)
        base.alpha_composite(ov)
        draw_text(ImageDraw.Draw(base), (x0 + 128, y + 33), text, f, T["label"], T["label_stroke"], 5,
                  tracking=0.04, anchor_center=False)
    return base.convert("RGB")


# ------------------------------------------------------------------ labels overlay
def _road_anchor(major, x, y, search=170, rad=46):
    """Snap (x, y) to the nearest main-road pixel; direction from the local road pixels."""
    H_, W_ = major.shape
    x0, y0 = max(0, int(x) - search), max(0, int(y) - search)
    sub = major[y0:int(y) + search, x0:int(x) + search] > 0.5
    ys, xs = np.nonzero(sub)
    if len(xs) == 0:
        raise ValueError("no road near %s" % ((x, y),))
    k = np.argmin((xs + x0 - x) ** 2 + (ys + y0 - y) ** 2)
    sx, sy = xs[k] + x0, ys[k] + y0
    sub = major[max(0, sy - rad):sy + rad, max(0, sx - rad):sx + rad] > 0.5
    ys, xs = np.nonzero(sub)
    pts = np.stack([xs, ys], 1).astype(float)
    pts -= pts.mean(0)
    w, v = np.linalg.eigh(pts.T @ pts)
    d = v[:, np.argmax(w)]
    ang = math.degrees(math.atan2(d[1], d[0]))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    return sx, sy, ang


def road_placements(major):
    out = []
    size, style, sw = ROAD_STYLE
    f = font(size, style)
    for text, x, y, side in ROAD_LABELS:
        sx, sy, ang = _road_anchor(major, x, y)
        a = math.radians(ang)
        nx, ny = -math.sin(a), math.cos(a)                  # normal (image coords)
        off = side * (size * 0.5 + 16)
        out.append((text, sx + nx * off, sy + ny * off, ang))
    return out


def label_shapes(major):
    """District + road labels as polygons (map px): [dict(kind, text, core, halo)].
    kind "label" (core + halo) or "water" (core only). The texture overlay and the vector
    tiles are both made from these, so the labels look the same at every zoom level."""
    import textgeo as tg
    out = []
    for text, x, y, kind in LABELS:
        sz, style, sw = STYLE[kind]
        if kind == "water":
            core = tg.place(tg.text_shape(text, sz, style, tracking=0.25), x, y)
            out.append(dict(kind="water", text=text, core=core, halo=None))
        else:
            sh = tg.text_shape(text, sz, style)
            out.append(dict(kind="label", text=text, core=tg.place(sh, x, y), halo=tg.place(tg.halo_of(sh, sw), x, y)))
    size, style, sw = ROAD_STYLE
    for text, cx, cy, ang in road_placements(major):
        sh = tg.text_shape(text, size, style, tracking=0.06)
        out.append(dict(kind="label", text=text, core=tg.place(sh, cx, cy, ang), halo=tg.place(tg.halo_of(sh, sw), cx, cy, ang)))
    return out


def overlay_masks(size, shapes):
    """Masks of all district + road labels: core (label colour), halo (stroke), water (water labels)."""
    import textgeo as tg
    core = tg.rasterize([d["core"] for d in shapes if d["kind"] == "label"], size)
    halo = tg.rasterize([d["halo"] for d in shapes if d["kind"] == "label"], size)
    water = tg.rasterize([d["core"] for d in shapes if d["kind"] == "water"], size)
    return core, halo, water


def legend_mask(size):
    return np.asarray(legend(None, None, mask=Image.new("L", size, 0))).astype(np.float32) / 255.0
