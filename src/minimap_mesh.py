"""Parse the vanilla vector minimap tiles (x64e.rpf/levels/gta5/minimap.rpf/minimap_X_Y.ydd).

Each tile is a drawable dictionary; every drawable holds flat coloured meshes
(vertex = float3 position + RGBA colour bytes). Returns triangles with colours in world space.
"""
import struct
import sys
import numpy as np
from ytd import read_rsc


def _sys(r, ptr):
    assert (ptr >> 28) == 5, hex(ptr)
    return ptr & 0x0FFFFFFF


def parse(path):
    r = read_rsc(path)
    s = r["sys"]
    rd = lambda fmt, off: struct.unpack_from(fmt, s, off)
    hptr, hcnt = rd("<QH", 0x20)
    dptr, dcnt = rd("<QH", 0x30)
    hashes = rd("<%dI" % hcnt, _sys(r, hptr))
    dptrs = rd("<%dQ" % dcnt, _sys(r, dptr))
    out = []
    for di, dp in enumerate(dptrs):
        d = _sys(r, dp)
        sg = rd("<Q", d + 0x10)[0]
        high = rd("<Q", d + 0x50)[0]
        name_ptr = rd("<Q", d + 0xA8)[0]
        name = None
        if name_ptr:
            no = _sys(r, name_ptr)
            name = s[no:s.index(b"\0", no)].decode("ascii", "replace")
        if not high:
            continue
        lp, lc = rd("<QH", _sys(r, high))
        for mp in rd("<%dQ" % lc, _sys(r, lp)):
            m = _sys(r, mp)
            gp, gc = rd("<QH", m + 0x08)
            smap = rd("<Q", m + 0x20)[0]
            shader_ids = rd("<%dH" % gc, _sys(r, smap)) if smap else [0] * gc
            for gi, g in enumerate(rd("<%dQ" % gc, _sys(r, gp))):
                g = _sys(r, g)
                vb = _sys(r, rd("<Q", g + 0x18)[0])
                ib = _sys(r, rd("<Q", g + 0x38)[0])
                stride, flags = rd("<HH", vb + 0x08)
                vdata, vcount = rd("<QI", vb + 0x10)
                info = _sys(r, rd("<Q", vb + 0x30)[0])
                dflags, dstride = rd("<IH", info)
                icount = rd("<I", ib + 0x08)[0]
                iptr = rd("<Q", ib + 0x10)[0]
                raw = np.frombuffer(s, np.uint8, vcount * stride, _sys(r, vdata)).reshape(vcount, stride)
                pos = raw[:, 0:12].copy().view(np.float32).reshape(vcount, 3)
                col = raw[:, 12:16].copy() if stride >= 16 else np.full((vcount, 4), 255, np.uint8)
                idx = np.frombuffer(s, np.uint16, icount, _sys(r, iptr)).reshape(-1, 3)
                out.append(dict(drawable=di, hash=hashes[di], name=name, geom=gi, shader=shader_ids[gi],
                                stride=stride, declflags=dflags, pos=pos, col=col, tris=idx))
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        geoms = parse(p)
        print("==", p, len(geoms), "geometries")
        allp = np.concatenate([g["pos"] for g in geoms])
        print("   bounds x %.1f..%.1f  y %.1f..%.1f  z %s" % (allp[:, 0].min(), allp[:, 0].max(), allp[:, 1].min(), allp[:, 1].max(),
                                                         np.unique(np.round(allp[:, 2], 2))[:12]))
        for g in geoms[:40]:
            cols = np.unique(g["col"].view(np.uint32))
            print("   d%-2d %-10s g%d sh%d stride%d decl=%x verts=%d tris=%d z=%s cols=%s" % (
                g["drawable"], hex(g["hash"]), g["geom"], g["shader"], g["stride"], g["declflags"], len(g["pos"]),
                len(g["tris"]), np.unique(g["pos"][:, 2])[:4], [hex(c) for c in cols[:4]]))
