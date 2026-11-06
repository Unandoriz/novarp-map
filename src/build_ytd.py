"""Cut the rendered map into minimap tiles and pack them into .ytd files.

Each output .ytd reuses the vanilla file's system segment (texture dictionary
layout, names, hashes) with patched texture size fields, so the structure stays
identical to what the game ships.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib
import numpy as np
from PIL import Image

from ytd import parse_ytd, tex_to_image, mip_size

TEXCONV = os.path.abspath("tools/texconv/texconv.exe")
GAME = "files/game"
FMT = {"DXT1": "BC1_UNORM", "DXT5": "BC3_UNORM"}


def flags_for(size, version_nibble):
    """Single-page RSC7 flags for a segment of `size` bytes (size must be 0x200<<ss * 256)."""
    ss = 0
    while (0x200 << ss) * 256 < size:
        ss += 1
    assert (0x200 << ss) * 256 == size, size
    return (version_nibble << 28) | (1 << 4) | ss


def dds_payload(img, fmt):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.png")
        img.save(p)
        subprocess.run([TEXCONV, "-nologo", "-y", "-f", FMT[fmt], "-m", "1", "-o", td, p],
                       check=True, stdout=subprocess.DEVNULL)
        d = open(os.path.join(td, "t.dds"), "rb").read()
    assert d[:4] == b"DDS "
    off = 128
    if d[84:88] == b"DX10":
        off += 20
    return d[off:]


def build(vanilla_path, img, out_path, size=None):
    r = parse_ytd(vanilla_path)
    t = r["textures"][0]
    fmt = t["fmtname"]
    w, h = size or (t["width"], t["height"])
    img = img.convert("RGBA").resize((w, h), Image.LANCZOS) if img.size != (w, h) else img.convert("RGBA")
    data = dds_payload(img, fmt)
    need = mip_size(t["format"], w, h)
    assert len(data) == need, (len(data), need)

    sysb = bytearray(r["sys"])
    o = t["sys_offset"]
    stride = need // h
    struct.pack_into("<HHHH", sysb, o + 0x50, w, h, 1, stride)
    sysb[o + 0x5D] = 1
    # usage: low bits as vanilla, size hint = page-rounded data size (min 32K) as in vanilla files
    usage = struct.unpack_from("<I", sysb, o + 0x40)[0]
    hint = 0x8000
    while hint < need:
        hint <<= 1
    usage = (usage & 0xE000001F) | (hint if need >= 0x8000 else (usage & 0x1FFFFFE0))
    struct.pack_into("<I", sysb, o + 0x40, usage)

    gsize = r["gfxsize"]
    while gsize < need:
        gsize *= 2
    gfx = data + b"\0" * (gsize - len(data))
    gflags = r["gfxflags"] if gsize == r["gfxsize"] else flags_for(gsize, r["gfxflags"] >> 28)
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = comp.compress(bytes(sysb) + gfx) + comp.flush()
    hdr = struct.pack("<IIII", 0x37435352, r["version"], r["sysflags"], gflags)
    open(out_path, "wb").write(hdr + body)

    # verify round trip
    chk = parse_ytd(out_path)
    ct = chk["textures"][0]
    assert (ct["width"], ct["height"], ct["name"]) == (w, h, t["name"])
    dec = np.asarray(tex_to_image(chk, ct).convert("RGB")).astype(np.int16)
    src = np.asarray(img.convert("RGB")).astype(np.int16)
    err = np.abs(dec - src).mean()
    return dict(name=t["name"], w=w, h=h, fmt=fmt, bytes=len(hdr) + len(body), err=float(err))


def main(themes):
    for theme in themes:
        full = Image.open("build/map_%s.png" % theme).convert("RGBA")
        W, H = full.size
        tw, th = W // 2, H // 3
        out = "dist/ytd/%s" % theme
        os.makedirs(out, exist_ok=True)
        # low-res tiles are opaque in vanilla (DXT1, sea baked in): flatten onto the deep sea colour
        from render import THEMES
        deep = tuple(THEMES[theme.split("_")[0]]["ocean_deep"]) + (255,)
        small = Image.new("RGBA", (1024, 1536), deep)
        small.alpha_composite(full.resize((1024, 1536), Image.LANCZOS))
        for row in range(3):
            for colm in range(2):
                tile = full.crop((colm * tw, row * th, (colm + 1) * tw, (row + 1) * th))
                info = build("%s/minimap_sea_%d_%d.ytd" % (GAME, row, colm), tile,
                             "%s/minimap_sea_%d_%d.ytd" % (out, row, colm), size=(tw, th))
                print(theme, info)
                lo = small.crop((colm * 512, row * 512, (colm + 1) * 512, (row + 1) * 512))
                info = build("%s/minimap_%d_%d.ytd" % (GAME, row, colm), lo,
                             "%s/minimap_%d_%d.ytd" % (out, row, colm))
                print(theme, info)
        info = build("%s/minimap_lod_128.ytd" % GAME, small.resize((128, 128), Image.LANCZOS),
                     "%s/minimap_lod_128.ytd" % out)
        print(theme, info)


if __name__ == "__main__":
    from render import VARIANTS
    main(sys.argv[1:] or VARIANTS)
