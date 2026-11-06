"""Minimal GTA V .ytd (RSC7 texture dictionary) reader/writer for legacy (gen8) PC resources."""
import struct
import zlib
import io

SYS_BASE = 0x50000000
GFX_BASE = 0x60000000

FMT_NAMES = {
    0x31545844: "DXT1", 0x33545844: "DXT3", 0x35545844: "DXT5",
    0x31495441: "ATI1", 0x32495441: "ATI2", 0x20374342: "BC7",
    21: "A8R8G8B8", 22: "X8R8G8B8", 25: "A1R5G5B5", 28: "A8", 50: "L8", 32: "A8B8G8R8",
}


def rsc_size(flags):
    s0 = ((flags >> 27) & 0x1) << 0
    s1 = ((flags >> 26) & 0x1) << 1
    s2 = ((flags >> 25) & 0x1) << 2
    s3 = ((flags >> 24) & 0x1) << 3
    s4 = ((flags >> 17) & 0x7F) << 4
    s5 = ((flags >> 11) & 0x3F) << 5
    s6 = ((flags >> 7) & 0xF) << 6
    s7 = ((flags >> 5) & 0x3) << 7
    s8 = ((flags >> 4) & 0x1) << 8
    ss = flags & 0xF
    return (0x200 << ss) * (s0 + s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8)


def read_rsc(path_or_bytes):
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
    magic, ver, sysf, gfxf = struct.unpack_from("<IIII", data, 0)
    assert magic == 0x37435352, "not RSC7"
    raw = zlib.decompress(data[16:], -15)
    ss, gs = rsc_size(sysf), rsc_size(gfxf)
    return dict(version=ver, sysflags=sysf, gfxflags=gfxf, sys=raw[:ss], gfx=raw[ss:ss + gs], raw=raw, syssize=ss, gfxsize=gs)


def mip_size(fmt, w, h):
    name = FMT_NAMES.get(fmt, str(fmt))
    if name in ("DXT1", "ATI1"):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if name in ("DXT3", "DXT5", "ATI2", "BC7"):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    if name in ("A8", "L8"):
        return w * h
    if name == "A1R5G5B5":
        return w * h * 2
    return w * h * 4


def parse_ytd(path_or_bytes):
    r = read_rsc(path_or_bytes)
    sysb, gfxb = r["sys"], r["gfx"]

    def sys_off(ptr):
        assert (ptr >> 28) == 5, hex(ptr)
        return ptr & 0x0FFFFFFF

    vft, u4, pages = struct.unpack_from("<IIQ", sysb, 0)
    hptr, hcnt, hcap = struct.unpack_from("<QHH", sysb, 0x20)
    tptr, tcnt, tcap = struct.unpack_from("<QHH", sysb, 0x30)
    hashes = list(struct.unpack_from("<%dI" % hcnt, sysb, sys_off(hptr)))
    tptrs = list(struct.unpack_from("<%dQ" % tcnt, sysb, sys_off(tptr)))
    texs = []
    for i, p in enumerate(tptrs):
        o = sys_off(p)
        nameptr = struct.unpack_from("<Q", sysb, o + 0x28)[0]
        no = sys_off(nameptr)
        name = sysb[no:sysb.index(b"\0", no)].decode("ascii")
        w, h, d, stride, fmt = struct.unpack_from("<HHHHI", sysb, o + 0x50)
        levels = sysb[o + 0x5D]
        dptr = struct.unpack_from("<Q", sysb, o + 0x70)[0]
        assert (dptr >> 28) == 6
        doff = dptr & 0x0FFFFFFF
        total = 0
        mw, mh = w, h
        for _ in range(levels):
            total += mip_size(fmt, mw, mh)
            mw, mh = max(1, mw // 2), max(1, mh // 2)
        texs.append(dict(index=i, name=name, hash=hashes[i] if i < len(hashes) else None, width=w, height=h,
                         depth=d, stride=stride, format=fmt, fmtname=FMT_NAMES.get(fmt, str(fmt)), levels=levels,
                         sys_offset=o, data_offset=doff, data_size=total,
                         usage=struct.unpack_from("<I", sysb, o + 0x40)[0]))
    r["textures"] = texs
    return r


def tex_to_image(r, t, level=0):
    """Decode mip `level` of texture t to a PIL image via a synthetic DDS header."""
    from PIL import Image
    fmt = t["fmtname"]
    w, h = t["width"], t["height"]
    off = t["data_offset"]
    for _ in range(level):
        off += mip_size(t["format"], w, h)
        w, h = max(1, w // 2), max(1, h // 2)
    size = mip_size(t["format"], w, h)
    pix = r["gfx"][off:off + size]
    if fmt in ("DXT1", "DXT3", "DXT5"):
        return Image.frombytes("RGBA", (w, h), pix, "bcn", {"DXT1": 1, "DXT3": 2, "DXT5": 3}[fmt])
    if fmt == "ATI1":
        return Image.frombytes("L", (w, h), pix, "bcn", 4)
    if fmt == "BC7":
        return Image.frombytes("RGBA", (w, h), pix, "bcn", 7)
    if fmt == "A8R8G8B8":
        return Image.frombytes("RGBA", (w, h), pix, "raw", "BGRA")
    if fmt in ("A8", "L8"):
        return Image.frombytes("L", (w, h), pix)
    raise ValueError("unsupported format " + fmt)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        r = parse_ytd(p)
        print(p, "ver", r["version"], "sys", r["syssize"], "gfx", r["gfxsize"])
        for t in r["textures"]:
            print("   ", t["name"], t["width"], "x", t["height"], t["fmtname"], "levels", t["levels"], "stride", t["stride"],
                  "data@", hex(t["data_offset"]), t["data_size"], "usage", hex(t["usage"]))
