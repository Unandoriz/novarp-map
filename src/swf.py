"""Tiny SWF/GFX (Scaleform) tag lister for inspection."""
import struct
import sys
import zlib
from collections import Counter

TAGS = {0: "End", 1: "ShowFrame", 2: "DefineShape", 4: "PlaceObject", 5: "RemoveObject", 9: "SetBackgroundColor",
        12: "DoAction", 22: "DefineShape2", 26: "PlaceObject2", 28: "RemoveObject2", 32: "DefineShape3",
        36: "DefineBitsLossless2", 37: "DefineEditText", 39: "DefineSprite", 43: "FrameLabel", 56: "ExportAssets",
        57: "ImportAssets", 59: "DoInitAction", 69: "FileAttributes", 70: "PlaceObject3", 71: "ImportAssets2",
        75: "DefineFont3", 76: "SymbolClass", 77: "Metadata", 82: "DoABC", 83: "DefineShape4", 86: "DefineSceneAndFrameLabelData",
        88: "DefineFontName", 1000: "GFX_ExporterInfo", 1001: "GFX_DefineExternalImage", 1002: "GFX_FontTextureInfo",
        1003: "GFX_DefineExternalGradient", 1004: "GFX_DefineGradientMap", 1005: "GFX_DefineCompactedFont",
        1006: "GFX_DefineExternalSound", 1007: "GFX_DefineExternalStreamSound", 1008: "GFX_DefineSubImage",
        1009: "GFX_DefineExternalImage2"}


def body(path):
    d = open(path, "rb").read()
    sig, ver, flen = d[:3], d[3], struct.unpack_from("<I", d, 4)[0]
    data = d[8:]
    if sig[:1] in (b"C",):
        data = zlib.decompress(data)
    return sig, ver, data


def rect_len(data, off):
    nbits = data[off] >> 3
    total = 5 + 4 * nbits
    return (total + 7) // 8


def tags(data, off, end):
    while off < end:
        cl = struct.unpack_from("<H", data, off)[0]
        off += 2
        code, ln = cl >> 6, cl & 0x3F
        if ln == 0x3F:
            ln = struct.unpack_from("<I", data, off)[0]
            off += 4
        yield code, data[off:off + ln], off
        off += ln
        if code == 0:
            break


def walk(data, off, end, depth, counter, out):
    for code, b, o in tags(data, off, end):
        counter[TAGS.get(code, str(code))] += 1
        if code == 39:  # sprite: id, framecount, tags
            sid = struct.unpack_from("<H", b, 0)[0]
            walk(data, o + 4, o + len(b), depth + 1, counter, out)
        elif code in (56, 57, 71, 1001, 1009, 76, 88, 43):
            out.append((TAGS.get(code, code), b[:200]))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        sig, ver, data = body(p)
        off = rect_len(data, 0) + 4
        c = Counter()
        out = []
        walk(data, off, len(data), 0, c, out)
        print("==", p, sig, ver, len(data))
        print("  ", dict(c.most_common(30)))
        for name, b in out[:25]:
            print("   ", name, b.replace(b"\0", b"|")[:160])
