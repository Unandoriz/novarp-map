"""City borders (Los Santos, Sandy Shores, Paleto Bay) from the game's own zone boxes
(update.rpf/common/data/levels/gta5/popzone.ipl). Only the parts that run over land are kept:
along the coast the shoreline already shows the edge.

Writes build/borders.json: {name: [polyline, ...]} in map pixels (4096 x 6144).
"""
import json
import numpy as np
import cv2
from layers import W, H, X0, Y0, MPP

LS_CODES = {
    "Richm", "Golf", "Rockf", "PBluff", "DTVine", "WVine", "Hors", "Burton", "Hawick", "East_V",
    "Morn", "Alta", "Mirr", "Movie", "DelPe", "Vine", "Koreat", "LMesa", "Downt", "PBOX", "TEXTI",
    "DeLBe", "VCana", "Murri", "Delbe", "LegSqu", "SKID", "Beach", "EBuro", "Vesp", "STRAW",
    "DelSol", "LosPuer", "RANCHO", "ChamH", "Davis", "Cypre", "Stad", "AirP", "Banning", "Elysian",
    "ZP_ORT", "Termina",
}
GROUPS = {"ls": LS_CODES, "sandy": {"Sandy"}, "paleto": {"Paleto"}}


def boxes():
    out = []
    for line in open("files/game/zones/popzone.ipl", encoding="latin-1"):
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 9:
            out.append((p[7], float(p[1]), float(p[2]), float(p[4]), float(p[5])))
    return out


def to_px(x, y):
    return (x - X0) / MPP, (Y0 - y) / MPP


def masks():
    res = {}
    allb = boxes()
    for name, codes in GROUPS.items():
        m = np.zeros((H, W), np.uint8)
        for code, x0, y0, x1, y1 in allb:
            if code not in codes:
                continue
            a = to_px(x0, y1)
            b = to_px(x1, y0)
            cv2.rectangle(m, (int(round(a[0])), int(round(a[1]))), (int(round(b[0])), int(round(b[1]))), 255, -1)
        # close tiny gaps between boxes and round the staircase corners a little
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        m = (cv2.GaussianBlur(m.astype(np.float32), (0, 0), 6) > 127).astype(np.uint8) * 255
        res[name] = m
    return res


def land_polylines(mask, land, min_len=12):
    """Contour of `mask`, split into runs that lie on land (both sides), simplified."""
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    solid = cv2.erode((land > 0.5).astype(np.uint8), np.ones((9, 9), np.uint8))
    out = []
    for c in cs:
        pts = c[:, 0, :]
        ok = solid[np.clip(pts[:, 1], 0, H - 1), np.clip(pts[:, 0], 0, W - 1)] > 0
        run = []
        for p, k in zip(pts, ok):
            if k:
                run.append(p)
            elif run:
                if len(run) >= min_len:
                    out.append(np.array(run))
                run = []
        if run and len(run) >= min_len:
            out.append(np.array(run))
    # drop runs that just follow the shoreline
    water = (land < 0.5).astype(np.uint8)
    near_water = cv2.dilate(water, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))) > 0
    out = [r for r in out if near_water[r[:, 1], r[:, 0]].mean() < 0.6]
    simp = []
    for r in out:
        a = cv2.approxPolyDP(r.reshape(-1, 1, 2).astype(np.int32), 1.5, False)[:, 0, :]
        simp.append(a.astype(float).tolist())
    return simp


def main():
    L = np.load("build/layers.npz")
    land = L["land"].astype(np.float32)
    res = {name: land_polylines(m, land) for name, m in masks().items()}
    json.dump(res, open("build/borders.json", "w"))
    for k, v in res.items():
        print(k, len(v), "polylines,", sum(len(p) for p in v), "points")


if __name__ == "__main__":
    main()
