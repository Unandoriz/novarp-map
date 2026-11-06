"""Structural check of the expected vector tiles (build/vector_expected/*/*.sys) against vanilla.

* page flags match the segment size, every pointer lands inside it, the root is at offset 0;
* merged tiles: the dictionary holds the merged drawable (all non-sea models) + the sea drawables,
  and the sea drawables keep their vanilla bounds and geometry (never extended);
* every vanilla geometry is still there with unchanged positions.
"""
import glob
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
from ydd_zones import read_rsc, vanilla_geometries, P, u64  # noqa: E402
import vector_plan as vp  # noqa: E402


def geometry_z(s, d):
    model = P(u64(s, P(u64(s, P(u64(s, d + 0x50))))))
    g = P(u64(s, P(u64(s, model + 0x08))))
    vb = P(u64(s, g + 0x18))
    vptr, n = struct.unpack_from("<QI", s, vb + 0x10)
    return float(np.median(np.frombuffer(s, np.float32, n * 4, P(vptr)).reshape(-1, 4)[:, 2]))


def main():
    merged = 0
    sizes = {}
    for d in sorted(os.listdir("build/vector_expected")):
        for f in sorted(glob.glob("build/vector_expected/%s/*.sys" % d)):
            b = open(f, "rb").read()
            s, flags = b[:-4], struct.unpack("<I", b[-4:])[0]
            c = [(flags >> vp.FLAG_SHIFT[k]) & vp.PAGE_MAX[k] for k in range(5)]
            assert sum(c[k] * vp.PAGE_SIZES[k] for k in range(5)) == len(s), f
            vs = read_rsc("files/game/minimap_ydd/" + os.path.basename(f)[:-4])["sys"]
            # pointers (the whole vanilla hash array is skipped: a hash + padding can look like one)
            hp = u64(s, 0x20) & 0xFFFFFFF
            hc = struct.unpack_from("<H", vs, 0x28)[0]
            w = np.frombuffer(s[:len(s) // 8 * 8], np.uint64)
            pos = np.arange(len(w)) * 8
            m = ((w >> np.uint64(28)) == 5) & ((w >> np.uint64(32)) == 0) & ((pos + 8 <= hp) | (pos >= hp + 4 * hc))
            assert ((w[m] & np.uint64(0x0FFFFFFF)) < len(s)).all(), f
            assert s[0:8] == vs[0:8], f
            pi = u64(s, 8) & 0x0FFFFFFF
            assert s[pi + 8] == sum(c), (f, "page info")
            # dictionary / models
            vdp, vdc = struct.unpack_from("<QH", vs, 0x30)
            vz = [geometry_z(vs, P(u64(vs, P(vdp) + 8 * i))) for i in range(vdc)]
            nsea = sum(z <= -0.5 for z in vz)
            dp, dc = struct.unpack_from("<QH", s, 0x30)
            counts = [struct.unpack_from("<H", s, P(u64(s, P(u64(s, P(dp) + 8 * i)) + 0x50)) + 8)[0] for i in range(dc)]
            if counts != [1] * vdc:
                assert dc == 1 + nsea and struct.unpack_from("<H", s, 0x28)[0] == dc, (f, dc, nsea)
                assert sorted(counts) == [1] * nsea + [vdc - nsea], (f, counts)
                vsea = sorted(vs[dd + 0x20:dd + 0x50] for dd in (P(u64(vs, P(vdp) + 8 * i)) for i in range(vdc)) if geometry_z(vs, dd) <= -0.5)
                nsea_b = sorted(s[dd + 0x20:dd + 0x50] for dd, k in ((P(u64(s, P(dp) + 8 * i)), counts[i]) for i in range(dc)) if k == 1)
                assert vsea == nsea_b, (f, "sea bounds changed")
                merged += 1
            # geometries: all vanilla ones still there, positions unchanged, the sea never extended
            g1 = [np.frombuffer(vs, np.float32, n * 4, o).reshape(-1, 4)[:, :3] for o, n, _ in vanilla_geometries(vs)]
            g2 = [np.frombuffer(s, np.float32, n * 4, o).reshape(-1, 4)[:, :3] for o, n, _ in vanilla_geometries(s)]
            assert len(g1) == len(g2), f
            used = set()
            for a in g1:
                hit = [j for j, bb in enumerate(g2) if j not in used and len(bb) >= len(a) and np.array_equal(bb[:len(a)], a)]
                assert hit, (f, "lost geometry")
                used.add(hit[0])
                if np.median(a[:, 2]) <= -0.5:
                    assert len(g2[hit[0]]) == len(a), (f, "sea geometry extended")
            sizes[d] = sizes.get(d, (0, 0))
            sizes[d] = (sizes[d][0] + len(vs), sizes[d][1] + len(s))
    print("all ok; merged tiles:", merged)
    for d, (a, b) in sizes.items():
        print("  %-16s system data %.2f -> %.2f MB" % (d, a / 1e6, b / 1e6))


if __name__ == "__main__":
    main()
