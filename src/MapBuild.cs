// Install-time map building:
//  * VectorPlan: rebuilds the vanilla vector minimap tiles (minimap_X_Y.ydd) for a theme and
//    options from build/vector_plan.bin (made by src/vector_plan.py; apply_plan() there is the
//    reference implementation of Apply()).
//  * TextureOverlay: composites the optional overlays (district/road names, square grid) onto
//    the prebuilt DXT texture tiles; only 4x4 blocks touched by an overlay are re-encoded.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;

namespace NovaMap
{
    public static class Rsc7
    {
        public class Res { public uint Version, SysFlags, GfxFlags; public byte[] Sys, Gfx; }

        public static Res Read(byte[] file)
        {
            if (BitConverter.ToUInt32(file, 0) != 0x37435352) throw new Exception("not RSC7");
            var r = new Res();
            r.Version = BitConverter.ToUInt32(file, 4);
            r.SysFlags = BitConverter.ToUInt32(file, 8);
            r.GfxFlags = BitConverter.ToUInt32(file, 12);
            byte[] raw = Crypto.Inflate(file, 16);
            int ss = Rsc.GetSize(r.SysFlags), gs = Rsc.GetSize(r.GfxFlags);
            r.Sys = new byte[ss];
            Buffer.BlockCopy(raw, 0, r.Sys, 0, ss);
            r.Gfx = new byte[gs];
            Buffer.BlockCopy(raw, ss, r.Gfx, 0, Math.Min(gs, raw.Length - ss));
            return r;
        }

        public static byte[] Write(Res r)
        {
            if (Rsc.GetSize(r.SysFlags) != r.Sys.Length || Rsc.GetSize(r.GfxFlags) != r.Gfx.Length)
                throw new Exception("RSC7 size mismatch");
            var body = new byte[r.Sys.Length + r.Gfx.Length];
            Buffer.BlockCopy(r.Sys, 0, body, 0, r.Sys.Length);
            Buffer.BlockCopy(r.Gfx, 0, body, r.Sys.Length, r.Gfx.Length);
            byte[] comp = Crypto.Deflate(body);
            var outp = new byte[16 + comp.Length];
            Buffer.BlockCopy(BitConverter.GetBytes(0x37435352u), 0, outp, 0, 4);
            Buffer.BlockCopy(BitConverter.GetBytes(r.Version), 0, outp, 4, 4);
            Buffer.BlockCopy(BitConverter.GetBytes(r.SysFlags), 0, outp, 8, 4);
            Buffer.BlockCopy(BitConverter.GetBytes(r.GfxFlags), 0, outp, 12, 4);
            Buffer.BlockCopy(comp, 0, outp, 16, comp.Length);
            return outp;
        }
    }

    // ================================================================== vector tiles
    public class VectorPlan
    {
        public const int MaxV = 4096, MaxI = 16384;

        public class Theme
        {
            public string Name;
            public byte[] LandLut, WaterLut;                  // 768 each, indexed by the vanilla grey level
            public byte[][] LayerColours;                     // [layer] -> rgb
            public byte[][] OverlayColours = new byte[5][];   // label, label stroke, water label, grid, grid halo
        }

        public class Piece
        {
            public int Layer;
            public float[] XY;       // 2 per vertex
            public ushort[] Idx;
        }

        public class Host { public int Index; public List<Piece> Pieces = new List<Piece>(); }

        public class TilePlan { public int[] Order; public List<Host> Hosts = new List<Host>(); }

        public float[] LayerZ;
        public List<Theme> Themes = new List<Theme>();
        public Dictionary<string, Dictionary<string, TilePlan>> Combos = new Dictionary<string, Dictionary<string, TilePlan>>();

        static string Str(BinaryReader r) { int n = r.ReadByte(); return Encoding.ASCII.GetString(r.ReadBytes(n)); }

        public static VectorPlan Load(byte[] zlibData)
        {
            byte[] raw = Crypto.Inflate(zlibData, 2);   // skip the zlib header
            var p = new VectorPlan();
            using (var r = new BinaryReader(new MemoryStream(raw)))
            {
                if (Encoding.ASCII.GetString(r.ReadBytes(4)) != "NVPL" || r.ReadUInt32() != 4) throw new Exception("bad vector plan");
                int nl = r.ReadByte();
                p.LayerZ = new float[nl];
                for (int l = 0; l < nl; l++) p.LayerZ[l] = r.ReadSingle();
                int nt = r.ReadByte();
                for (int t = 0; t < nt; t++)
                {
                    var th = new Theme();
                    th.Name = Str(r);
                    th.LandLut = r.ReadBytes(768);
                    th.WaterLut = r.ReadBytes(768);
                    th.LayerColours = new byte[nl][];
                    for (int l = 0; l < nl; l++) th.LayerColours[l] = r.ReadBytes(3);
                    for (int l = 0; l < 5; l++) th.OverlayColours[l] = r.ReadBytes(3);
                    p.Themes.Add(th);
                }
                int nc = r.ReadByte();
                for (int c = 0; c < nc; c++)
                {
                    int grid = r.ReadByte(), labels = r.ReadByte(), ntiles = r.ReadUInt16();
                    var tiles = new Dictionary<string, TilePlan>();
                    for (int i = 0; i < ntiles; i++)
                    {
                        string name = Str(r);
                        var tp = new TilePlan();
                        tp.Order = new int[r.ReadByte()];
                        for (int k = 0; k < tp.Order.Length; k++) tp.Order[k] = r.ReadUInt16();
                        int nh = r.ReadUInt16();
                        var hosts = tp.Hosts;
                        for (int h = 0; h < nh; h++)
                        {
                            var host = new Host { Index = r.ReadUInt16() };
                            int np = r.ReadUInt16();
                            for (int k = 0; k < np; k++)
                            {
                                var pc = new Piece { Layer = r.ReadByte() };
                                int nv = r.ReadUInt16(), ni = r.ReadUInt16();
                                pc.XY = new float[nv * 2];
                                for (int v = 0; v < nv * 2; v++) pc.XY[v] = r.ReadSingle();
                                pc.Idx = new ushort[ni];
                                for (int v = 0; v < ni; v++) pc.Idx[v] = r.ReadUInt16();
                                host.Pieces.Add(pc);
                            }
                            hosts.Add(host);
                        }
                        tiles[name] = tp;
                    }
                    p.Combos[grid + "_" + labels] = tiles;
                }
            }
            return p;
        }

        public int ThemeIndex(string theme)
        {
            for (int i = 0; i < Themes.Count; i++) if (Themes[i].Name == theme) return i;
            throw new Exception("Нет темы " + theme);
        }

        // ---- resource helpers (pointer = 0x50000000 + offset into the system segment)
        static int P(ulong p) { if ((p >> 28) != 5) throw new Exception("bad pointer"); return (int)(p & 0x0FFFFFFF); }
        static ulong U64(byte[] s, int o) { return BitConverter.ToUInt64(s, o); }

        class GeomInfo { public int Vptr, N, Stride; }

        class HostInfo
        {
            public int D, G, Bnd, Vb, Ib, Stride, Vptr, N, Iptr, M;
        }

        static List<GeomInfo> VanillaGeometries(byte[] s)
        {
            var outp = new List<GeomInfo>();
            int dp = P(U64(s, 0x30)), dc = BitConverter.ToUInt16(s, 0x38);
            for (int i = 0; i < dc; i++)
            {
                int d = P(U64(s, dp + 8 * i));
                int high = P(U64(s, d + 0x50));
                int lp = P(U64(s, high)), lc = BitConverter.ToUInt16(s, high + 8);
                for (int k = 0; k < lc; k++)
                {
                    int m = P(U64(s, lp + 8 * k));
                    int gp = P(U64(s, m + 0x08)), gc = BitConverter.ToUInt16(s, m + 0x10);
                    for (int j = 0; j < gc; j++)
                    {
                        int g = P(U64(s, gp + 8 * j));
                        int vb = P(U64(s, g + 0x18));
                        outp.Add(new GeomInfo { Stride = BitConverter.ToUInt16(s, vb + 0x08), Vptr = P(U64(s, vb + 0x10)), N = (int)BitConverter.ToUInt32(s, vb + 0x18) });
                    }
                }
            }
            return outp;
        }

        // drawables with exactly one model and one geometry, keyed by their index in the dictionary
        static Dictionary<int, HostInfo> Hosts(byte[] s)
        {
            var outp = new Dictionary<int, HostInfo>();
            int dp = P(U64(s, 0x30)), dc = BitConverter.ToUInt16(s, 0x38);
            for (int i = 0; i < dc; i++)
            {
                int d = P(U64(s, dp + 8 * i));
                int mb = P(U64(s, d + 0x50));
                int lp = P(U64(s, mb)), lc = BitConverter.ToUInt16(s, mb + 8);
                int m = P(U64(s, lp));
                int gp = P(U64(s, m + 0x08)), gc = BitConverter.ToUInt16(s, m + 0x10);
                if (lc != 1 || gc != 1) continue;
                var h = new HostInfo();
                h.D = d;
                h.G = P(U64(s, gp));
                h.Bnd = P(U64(s, m + 0x18));
                h.Vb = P(U64(s, h.G + 0x18));
                h.Ib = P(U64(s, h.G + 0x38));
                h.Stride = BitConverter.ToUInt16(s, h.Vb + 0x08);
                h.Vptr = P(U64(s, h.Vb + 0x10));
                h.N = (int)BitConverter.ToUInt32(s, h.Vb + 0x18);
                h.M = (int)BitConverter.ToUInt32(s, h.Ib + 0x08);
                h.Iptr = P(U64(s, h.Ib + 0x10));
                outp[i] = h;
            }
            return outp;
        }

        // New blocks go into new pages of the smallest class that fits (RSC7 classes 0..4 =
        // 128..8 KB); the pages are inserted after the vanilla pages of their class, so the data
        // behind them moves and every pointer into it is remapped (same as vector_plan.Relayout).
        class Relayout
        {
            public static readonly int[] Size = { 0x20000, 0x10000, 0x8000, 0x4000, 0x2000 };
            static readonly int[] Max = { 1, 3, 15, 63, 127 };
            static readonly int[] Shift = { 4, 5, 7, 11, 17 };
            public int[] C = new int[5];
            MemoryStream[] data = new MemoryStream[5];
            int[] cur = new int[5];
            List<int[]> blocks = new List<int[]>();
            int[] os = new int[5], ns = new int[5];
            uint flags;
            int oldLen;

            public Relayout(int len, uint fl)
            {
                if ((fl & 0xF) != 0 || ((fl >> 24) & 0xF) != 0) throw new Exception("unexpected page layout");
                flags = fl;
                oldLen = len;
                int total = 0;
                for (int k = 0; k < 5; k++)
                {
                    C[k] = (int)((fl >> Shift[k]) & (uint)Max[k]);
                    total += C[k] * Size[k];
                    data[k] = new MemoryStream();
                }
                if (total != len) throw new Exception("unexpected page layout");
            }

            public static int PageClass(int n)
            {
                for (int k = 4; k >= 0; k--) if (Size[k] >= n) return k;
                throw new Exception("block too large");
            }

            public int FirstClass() { for (int k = 0; k < 5; k++) if (C[k] > 0) return k; return 4; }

            public int Pages()
            {
                int n = 0;
                for (int k = 0; k < 5; k++) n += C[k] + (int)(data[k].Length / Size[k]);
                return n;
            }

            public int Alloc(byte[] b, int k = -1)
            {
                int n = b.Length;
                if (k < 0) k = PageClass(n);
                int size = Size[k];
                int off = (cur[k] + 15) / 16 * 16;
                if (off % size + n > size) off = (off / size + 1) * size;
                cur[k] = off + n;
                long need = (cur[k] + size - 1) / size * (long)size;
                if (data[k].Length < need) data[k].SetLength(need);
                data[k].Position = off;
                data[k].Write(b, 0, n);
                blocks.Add(new[] { k, off });
                return blocks.Count - 1;
            }

            public int Remap(int o)
            {
                for (int k = 0; k < 5; k++)
                    if (o >= os[k] && o < os[k] + C[k] * Size[k]) return o - os[k] + ns[k];
                throw new Exception("bad offset");
            }

            public int Block(int i) { int k = blocks[i][0]; return ns[k] + C[k] * Size[k] + blocks[i][1]; }

            // skipStart/skipEnd: a byte range without pointers (the dictionary's name hashes)
            public byte[] Finalize(byte[] old, int skipStart, int skipEnd, out uint newFlags)
            {
                int o = 0, n = 0;
                var add = new int[5];
                for (int k = 0; k < 5; k++)
                {
                    add[k] = (int)(data[k].Length / Size[k]);
                    if (C[k] + add[k] > Max[k]) throw new Exception("too many pages");
                    os[k] = o; ns[k] = n;
                    o += C[k] * Size[k];
                    n += (C[k] + add[k]) * Size[k];
                }
                var outp = new byte[n];
                for (int k = 0; k < 5; k++)
                {
                    int ln = C[k] * Size[k];
                    Buffer.BlockCopy(old, os[k], outp, ns[k], ln);
                    byte[] d = data[k].ToArray();
                    Buffer.BlockCopy(d, 0, outp, ns[k] + ln, d.Length);
                }
                for (int i = 0; i + 8 <= old.Length; i += 8)
                {
                    if (i + 8 > skipStart && i < skipEnd) continue;
                    ulong v = BitConverter.ToUInt64(old, i);
                    if ((v >> 32) != 0 || (v >> 28) != 5 || (long)(v & 0x0FFFFFFF) >= oldLen) continue;
                    PutU64(outp, Remap(i), 0x50000000UL + (ulong)Remap((int)(v & 0x0FFFFFFF)));
                }
                uint f = flags;
                for (int k = 0; k < 5; k++) f = (f & ~((uint)Max[k] << Shift[k])) | ((uint)(C[k] + add[k]) << Shift[k]);
                newFlags = f;
                return outp;
            }
        }

        static void PutF(byte[] s, int o, float v) { Buffer.BlockCopy(BitConverter.GetBytes(v), 0, s, o, 4); }
        static void PutU64(byte[] s, int o, ulong v) { Buffer.BlockCopy(BitConverter.GetBytes(v), 0, s, o, 8); }
        static void PutU32(byte[] s, int o, uint v) { Buffer.BlockCopy(BitConverter.GetBytes(v), 0, s, o, 4); }
        static void PutU16(byte[] s, int o, ushort v) { Buffer.BlockCopy(BitConverter.GetBytes(v), 0, s, o, 2); }

        const int RootSize = 0x40;   // pgDictionary<rmcDrawable>

        class Built { public HostInfo H; public int Index; public byte[] V, I; public int Nv, Ni, Bv, Bi; public double[] Mn, Mx; }

        // Returns the rebuilt system segment and flags for one tile (same as vector_plan.apply_plan):
        // our geometry appended to two models, the tile's land / building / road models in one
        // drawable in the plan's order, the dictionary reduced to that drawable + the untouched sea.
        public Rsc7.Res Apply(Rsc7.Res vanilla, string tileName, int theme, bool grid, bool labels)
        {
            var th = Themes[theme];
            byte[] s = (byte[])vanilla.Sys.Clone();
            foreach (var g in VanillaGeometries(s))
            {
                for (int v = 0; v < g.N; v++)
                {
                    int o = g.Vptr + v * g.Stride;
                    float z = BitConverter.ToSingle(s, o + 8);
                    int lum = (s[o + 12] + s[o + 13] + s[o + 14]) / 3;
                    byte[] lut = z < 0 ? th.WaterLut : th.LandLut;
                    s[o + 12] = lut[lum * 3]; s[o + 13] = lut[lum * 3 + 1]; s[o + 14] = lut[lum * 3 + 2];
                }
            }
            var res = new Rsc7.Res { Version = vanilla.Version, SysFlags = vanilla.SysFlags, GfxFlags = vanilla.GfxFlags, Gfx = vanilla.Gfx };
            TilePlan plan;
            if (!Combos[(grid ? 1 : 0) + "_" + (labels ? 1 : 0)].TryGetValue(tileName, out plan) || plan.Hosts.Count == 0)
            {
                res.Sys = s;
                return res;
            }
            var hosts = Hosts(s);
            var built = new List<Built>();
            foreach (var hp in plan.Hosts)
            {
                var h = hosts[hp.Index];
                int n = h.N, m = h.M;
                var vdat = new MemoryStream();
                vdat.Write(s, h.Vptr, n * 16);
                var idx = new List<ushort>();
                for (int k = 0; k < m; k++) idx.Add(BitConverter.ToUInt16(s, h.Iptr + 2 * k));
                int bse = n;
                var w = new BinaryWriter(vdat);
                foreach (var pc in hp.Pieces)
                {
                    float z = LayerZ[pc.Layer];
                    var cc = th.LayerColours[pc.Layer];
                    int nv = pc.XY.Length / 2;
                    for (int v = 0; v < nv; v++)
                    {
                        w.Write(pc.XY[2 * v]); w.Write(pc.XY[2 * v + 1]); w.Write(z);
                        w.Write(cc[0]); w.Write(cc[1]); w.Write(cc[2]); w.Write((byte)255);
                    }
                    foreach (var i in pc.Idx) idx.Add((ushort)(bse + i));
                    bse += nv;
                }
                w.Flush();
                if (bse > MaxV || idx.Count > MaxI) throw new Exception("vector capacity exceeded in " + tileName);
                var ib = new byte[idx.Count * 2];
                for (int k = 0; k < idx.Count; k++) Buffer.BlockCopy(BitConverter.GetBytes(idx[k]), 0, ib, 2 * k, 2);
                byte[] vb = vdat.ToArray();
                double[] mn, mx;
                MinMax(vb, 0, bse, out mn, out mx);
                built.Add(new Built { H = h, Index = hp.Index, V = vb, I = ib, Nv = bse, Ni = idx.Count, Mn = mn, Mx = mx });
            }
            var R = new Relayout(s.Length, vanilla.SysFlags);
            // the resource root must stay at offset 0, i.e. at the start of the first (largest) page:
            // when a new page is larger than every vanilla page, it gets a copy of the root struct
            int kNew = 4;
            foreach (var b in built) kNew = Math.Min(kNew, Math.Min(Relayout.PageClass(b.V.Length), Relayout.PageClass(b.I.Length)));
            int root = kNew < R.FirstClass() ? R.Alloc(new byte[RootSize], kNew) : -1;
            foreach (var b in built) { b.Bv = R.Alloc(b.V); b.Bi = R.Alloc(b.I); }
            int[] order = plan.Order;
            int bModels = R.Alloc(new byte[8 * order.Length]);
            int piOld = P(U64(s, 0x08));
            int est = R.Pages() + 1;
            int bp = R.Alloc(new byte[16 + 8 * est]);
            int sysPages = R.Pages();
            if (sysPages > est) throw new Exception("page info");
            int hp0 = P(U64(s, 0x20)), hc = BitConverter.ToUInt16(s, 0x28);
            uint flags;
            byte[] outp = R.Finalize(s, hp0, hp0 + 4 * hc, out flags);
            if (root >= 0)
            {
                if (R.Block(root) != 0) throw new Exception("root");
                Buffer.BlockCopy(outp, R.Remap(0), outp, 0, RootSize);
            }
            // point the extended geometries at their new buffers (struct offsets moved with the relayout)
            var ext = new Dictionary<int, Built>();
            foreach (var b in built)
            {
                var h = b.H;
                int vbo = R.Remap(h.Vb), ibo = R.Remap(h.Ib), g = R.Remap(h.G), bnd = R.Remap(h.Bnd);
                ulong pv = 0x50000000UL + (ulong)R.Block(b.Bv), pi = 0x50000000UL + (ulong)R.Block(b.Bi);
                PutU64(outp, vbo + 0x10, pv); PutU32(outp, vbo + 0x18, (uint)b.Nv); PutU64(outp, vbo + 0x20, pv);
                PutU32(outp, ibo + 0x08, (uint)b.Ni); PutU64(outp, ibo + 0x10, pi);
                PutU32(outp, g + 0x58, (uint)b.Ni); PutU32(outp, g + 0x5C, (uint)(b.Ni / 3));
                PutU16(outp, g + 0x60, (ushort)b.Nv);
                PutU64(outp, g + 0x78, pv);
                PutF(outp, bnd, (float)b.Mn[0]); PutF(outp, bnd + 4, (float)b.Mn[1]); PutF(outp, bnd + 8, (float)b.Mn[2]); PutF(outp, bnd + 12, (float)b.Mn[0]);
                PutF(outp, bnd + 16, (float)b.Mx[0]); PutF(outp, bnd + 20, (float)b.Mx[1]); PutF(outp, bnd + 24, (float)b.Mx[2]); PutF(outp, bnd + 28, (float)b.Mx[0]);
                ext[b.Index] = b;
            }
            // all models of the tile in the last drawable of the order
            var target = hosts[order[order.Length - 1]];
            double[] tmn = { double.PositiveInfinity, double.PositiveInfinity, double.PositiveInfinity };
            double[] tmx = { double.NegativeInfinity, double.NegativeInfinity, double.NegativeInfinity };
            for (int k = 0; k < order.Length; k++)
            {
                var h = hosts[order[k]];
                int mlist = P(U64(s, h.D + 0x50));
                int model = P(U64(s, P(U64(s, mlist))));
                PutU64(outp, R.Block(bModels) + 8 * k, 0x50000000UL + (ulong)R.Remap(model));
                double[] a, b2;
                Built e;
                if (ext.TryGetValue(order[k], out e)) { a = e.Mn; b2 = e.Mx; }
                else MinMax(s, h.Vptr, h.N, out a, out b2);
                for (int c = 0; c < 3; c++) { tmn[c] = Math.Min(tmn[c], a[c]); tmx[c] = Math.Max(tmx[c], b2[c]); }
            }
            int tl = R.Remap(P(U64(s, target.D + 0x50)));
            PutU64(outp, tl, 0x50000000UL + (ulong)R.Block(bModels));
            PutU16(outp, tl + 8, (ushort)order.Length); PutU16(outp, tl + 10, (ushort)order.Length);
            int d = R.Remap(target.D);
            double dx = tmx[0] - tmn[0], dy = tmx[1] - tmn[1], dz = tmx[2] - tmn[2];
            PutF(outp, d + 0x20, (float)((tmn[0] + tmx[0]) / 2)); PutF(outp, d + 0x24, (float)((tmn[1] + tmx[1]) / 2));
            PutF(outp, d + 0x28, (float)((tmn[2] + tmx[2]) / 2)); PutF(outp, d + 0x2C, (float)(Math.Sqrt(dx * dx + dy * dy + dz * dz) / 2));
            PutF(outp, d + 0x30, (float)tmn[0]); PutF(outp, d + 0x34, (float)tmn[1]); PutF(outp, d + 0x38, (float)tmn[2]);
            PutF(outp, d + 0x40, (float)tmx[0]); PutF(outp, d + 0x44, (float)tmx[1]); PutF(outp, d + 0x48, (float)tmx[2]);
            // the dictionary keeps the merged drawable and the sea ones (in their order: hashes stay sorted)
            int dp = P(U64(s, 0x30)), dc = BitConverter.ToUInt16(s, 0x38);
            var merged = new HashSet<int>(order);
            int kept = 0;
            for (int i = 0; i < dc; i++)
            {
                if (i != order[order.Length - 1] && merged.Contains(i)) continue;
                PutU32(outp, R.Remap(hp0) + 4 * kept, BitConverter.ToUInt32(s, hp0 + 4 * i));
                PutU64(outp, R.Remap(dp) + 8 * kept, 0x50000000UL + (ulong)R.Remap(P(U64(s, dp + 8 * i))));
                kept++;
            }
            PutU16(outp, 0x28, (ushort)kept);
            PutU16(outp, 0x38, (ushort)kept);
            // pages info: relocated, it lists one slot per page
            int oPi = R.Block(bp);
            Buffer.BlockCopy(s, piOld, outp, oPi, 16);
            outp[oPi + 8] = (byte)sysPages;
            outp[oPi + 9] = 0;
            PutU64(outp, 0x08, 0x50000000UL + (ulong)oPi);
            res.Sys = outp;
            res.SysFlags = flags;
            return res;
        }

        static void MinMax(byte[] s, int vptr, int n, out double[] mn, out double[] mx)
        {
            mn = new[] { double.PositiveInfinity, double.PositiveInfinity, double.PositiveInfinity };
            mx = new[] { double.NegativeInfinity, double.NegativeInfinity, double.NegativeInfinity };
            for (int v = 0; v < n; v++)
                for (int c = 0; c < 3; c++)
                {
                    double f = BitConverter.ToSingle(s, vptr + v * 16 + 4 * c);
                    mn[c] = Math.Min(mn[c], f); mx[c] = Math.Max(mx[c], f);
                }
        }
    }

    // ================================================================== DXT
    public static class Dxt
    {
        static void Unpack565(int c, out int r, out int g, out int b)
        {
            r = (c >> 11) & 31; g = (c >> 5) & 63; b = c & 31;
            r = (r << 3) | (r >> 2); g = (g << 2) | (g >> 4); b = (b << 3) | (b >> 2);
        }

        static int Pack565(double r, double g, double b)
        {
            int ri = Math.Max(0, Math.Min(31, (int)Math.Round(r * 31 / 255.0)));
            int gi = Math.Max(0, Math.Min(63, (int)Math.Round(g * 63 / 255.0)));
            int bi = Math.Max(0, Math.Min(31, (int)Math.Round(b * 31 / 255.0)));
            return (ri << 11) | (gi << 5) | bi;
        }

        // rgba: 64 bytes (16 px). fourColour: BC2/BC3 colour blocks are always 4-colour.
        public static void DecodeColour(byte[] blk, int o, byte[] rgba, bool fourColour)
        {
            int c0 = BitConverter.ToUInt16(blk, o), c1 = BitConverter.ToUInt16(blk, o + 2);
            uint bits = BitConverter.ToUInt32(blk, o + 4);
            int r0, g0, b0, r1, g1, b1;
            Unpack565(c0, out r0, out g0, out b0); Unpack565(c1, out r1, out g1, out b1);
            var pal = new int[16];
            pal[0] = r0; pal[1] = g0; pal[2] = b0; pal[3] = 255;
            pal[4] = r1; pal[5] = g1; pal[6] = b1; pal[7] = 255;
            if (fourColour || c0 > c1)
            {
                pal[8] = (2 * r0 + r1) / 3; pal[9] = (2 * g0 + g1) / 3; pal[10] = (2 * b0 + b1) / 3; pal[11] = 255;
                pal[12] = (r0 + 2 * r1) / 3; pal[13] = (g0 + 2 * g1) / 3; pal[14] = (b0 + 2 * b1) / 3; pal[15] = 255;
            }
            else
            {
                pal[8] = (r0 + r1) / 2; pal[9] = (g0 + g1) / 2; pal[10] = (b0 + b1) / 2; pal[11] = 255;
                pal[12] = 0; pal[13] = 0; pal[14] = 0; pal[15] = 0;
            }
            for (int i = 0; i < 16; i++)
            {
                int k = (int)((bits >> (2 * i)) & 3);
                rgba[4 * i] = (byte)pal[4 * k]; rgba[4 * i + 1] = (byte)pal[4 * k + 1]; rgba[4 * i + 2] = (byte)pal[4 * k + 2];
                if (!fourColour) rgba[4 * i + 3] = (byte)pal[4 * k + 3];
            }
        }

        public static void DecodeAlpha(byte[] blk, int o, byte[] rgba)
        {
            int a0 = blk[o], a1 = blk[o + 1];
            ulong bits = 0;
            for (int i = 0; i < 6; i++) bits |= (ulong)blk[o + 2 + i] << (8 * i);
            var pal = new int[8];
            pal[0] = a0; pal[1] = a1;
            if (a0 > a1) for (int i = 1; i < 7; i++) pal[i + 1] = ((7 - i) * a0 + i * a1) / 7;
            else { for (int i = 1; i < 5; i++) pal[i + 1] = ((5 - i) * a0 + i * a1) / 5; pal[6] = 0; pal[7] = 255; }
            for (int i = 0; i < 16; i++) rgba[4 * i + 3] = (byte)pal[(int)((bits >> (3 * i)) & 7)];
        }

        // Colour block encoder: principal axis endpoints + one least-squares refinement.
        public static void EncodeColour(byte[] rgba, byte[] outp, int o)
        {
            double mr = 0, mg = 0, mb = 0;
            for (int i = 0; i < 16; i++) { mr += rgba[4 * i]; mg += rgba[4 * i + 1]; mb += rgba[4 * i + 2]; }
            mr /= 16; mg /= 16; mb /= 16;
            double crr = 0, crg = 0, crb = 0, cgg = 0, cgb = 0, cbb = 0;
            for (int i = 0; i < 16; i++)
            {
                double r = rgba[4 * i] - mr, g = rgba[4 * i + 1] - mg, b = rgba[4 * i + 2] - mb;
                crr += r * r; crg += r * g; crb += r * b; cgg += g * g; cgb += g * b; cbb += b * b;
            }
            double vr = 1, vg = 1, vb = 1;
            for (int it = 0; it < 8; it++)
            {
                double nr = crr * vr + crg * vg + crb * vb, ng = crg * vr + cgg * vg + cgb * vb, nb = crb * vr + cgb * vg + cbb * vb;
                double len = Math.Sqrt(nr * nr + ng * ng + nb * nb);
                if (len < 1e-9) break;
                vr = nr / len; vg = ng / len; vb = nb / len;
            }
            double tmin = double.MaxValue, tmax = double.MinValue;
            for (int i = 0; i < 16; i++)
            {
                double t = (rgba[4 * i] - mr) * vr + (rgba[4 * i + 1] - mg) * vg + (rgba[4 * i + 2] - mb) * vb;
                tmin = Math.Min(tmin, t); tmax = Math.Max(tmax, t);
            }
            double[] e0 = { mr + vr * tmax, mg + vg * tmax, mb + vb * tmax };
            double[] e1 = { mr + vr * tmin, mg + vg * tmin, mb + vb * tmin };
            int c0 = Pack565(e0[0], e0[1], e0[2]), c1 = Pack565(e1[0], e1[1], e1[2]);
            uint bits = Indices(rgba, ref c0, ref c1);
            // least-squares refit of the endpoints for the chosen indices
            double a2 = 0, b2 = 0, ab = 0;
            double[] ax = new double[3], bx = new double[3];
            double[] wts = { 1, 0, 2.0 / 3, 1.0 / 3 };
            for (int i = 0; i < 16; i++)
            {
                double al = wts[(bits >> (2 * i)) & 3], be = 1 - al;
                a2 += al * al; b2 += be * be; ab += al * be;
                for (int c = 0; c < 3; c++) { ax[c] += al * rgba[4 * i + c]; bx[c] += be * rgba[4 * i + c]; }
            }
            double det = a2 * b2 - ab * ab;
            if (Math.Abs(det) > 1e-6)
            {
                var f0 = new double[3]; var f1 = new double[3];
                for (int c = 0; c < 3; c++) { f0[c] = (ax[c] * b2 - bx[c] * ab) / det; f1[c] = (bx[c] * a2 - ax[c] * ab) / det; }
                int n0 = Pack565(f0[0], f0[1], f0[2]), n1 = Pack565(f1[0], f1[1], f1[2]);
                uint nbits = Indices(rgba, ref n0, ref n1);
                if (Error(rgba, n0, n1, nbits) < Error(rgba, c0, c1, bits)) { c0 = n0; c1 = n1; bits = nbits; }
            }
            Buffer.BlockCopy(BitConverter.GetBytes((ushort)c0), 0, outp, o, 2);
            Buffer.BlockCopy(BitConverter.GetBytes((ushort)c1), 0, outp, o + 2, 2);
            Buffer.BlockCopy(BitConverter.GetBytes(bits), 0, outp, o + 4, 4);
        }

        // nearest-palette indices for 4-colour mode (makes sure c0 > c1)
        static uint Indices(byte[] rgba, ref int c0, ref int c1)
        {
            if (c0 < c1) { int t = c0; c0 = c1; c1 = t; }
            if (c0 == c1) return 0;
            int[] pal = Palette(c0, c1);
            uint bits = 0;
            for (int i = 0; i < 16; i++)
            {
                int best = 0, bd = int.MaxValue;
                for (int k = 0; k < 4; k++)
                {
                    int dr = rgba[4 * i] - pal[3 * k], dg = rgba[4 * i + 1] - pal[3 * k + 1], db = rgba[4 * i + 2] - pal[3 * k + 2];
                    int d = dr * dr + dg * dg + db * db;
                    if (d < bd) { bd = d; best = k; }
                }
                bits |= (uint)best << (2 * i);
            }
            return bits;
        }

        static int[] Palette(int c0, int c1)
        {
            int r0, g0, b0, r1, g1, b1;
            Unpack565(c0, out r0, out g0, out b0); Unpack565(c1, out r1, out g1, out b1);
            return new[] { r0, g0, b0, r1, g1, b1, (2 * r0 + r1) / 3, (2 * g0 + g1) / 3, (2 * b0 + b1) / 3, (r0 + 2 * r1) / 3, (g0 + 2 * g1) / 3, (b0 + 2 * b1) / 3 };
        }

        static long Error(byte[] rgba, int c0, int c1, uint bits)
        {
            int[] pal = Palette(c0, c1);
            long e = 0;
            for (int i = 0; i < 16; i++)
            {
                int k = (int)((bits >> (2 * i)) & 3);
                if (c0 == c1) k = 0;
                for (int c = 0; c < 3; c++) { int d = rgba[4 * i + c] - pal[3 * k + c]; e += d * d; }
            }
            return e;
        }

        public static void EncodeAlpha(byte[] rgba, byte[] outp, int o)
        {
            int a0 = 0, a1 = 255;
            for (int i = 0; i < 16; i++) { a0 = Math.Max(a0, rgba[4 * i + 3]); a1 = Math.Min(a1, rgba[4 * i + 3]); }
            outp[o] = (byte)a0; outp[o + 1] = (byte)a1;
            ulong bits = 0;
            if (a0 != a1)
            {
                var pal = new int[8];
                pal[0] = a0; pal[1] = a1;
                for (int i = 1; i < 7; i++) pal[i + 1] = ((7 - i) * a0 + i * a1) / 7;
                for (int i = 0; i < 16; i++)
                {
                    int best = 0, bd = int.MaxValue;
                    for (int k = 0; k < 8; k++) { int d = Math.Abs(rgba[4 * i + 3] - pal[k]); if (d < bd) { bd = d; best = k; } }
                    bits |= (ulong)best << (3 * i);
                }
            }
            for (int i = 0; i < 6; i++) outp[o + 2 + i] = (byte)(bits >> (8 * i));
        }
    }

    // ================================================================== texture overlays
    public class Overlay
    {
        public int W, H;
        public byte[] C0, C1, C2;   // channels R, G, B of the overlay image

        public static Overlay FromPng(byte[] png)
        {
            using (var ms = new MemoryStream(png))
            using (var bmp = new Bitmap(ms))
            {
                var o = new Overlay { W = bmp.Width, H = bmp.Height };
                var data = bmp.LockBits(new Rectangle(0, 0, o.W, o.H), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
                var row = new byte[data.Stride];
                o.C0 = new byte[o.W * o.H]; o.C1 = new byte[o.W * o.H]; o.C2 = new byte[o.W * o.H];
                for (int y = 0; y < o.H; y++)
                {
                    Marshal.Copy(data.Scan0 + y * data.Stride, row, 0, data.Stride);
                    for (int x = 0; x < o.W; x++)
                    {
                        int i = y * o.W + x;
                        o.C0[i] = row[3 * x + 2]; o.C1[i] = row[3 * x + 1]; o.C2[i] = row[3 * x];   // BGR in memory
                    }
                }
                bmp.UnlockBits(data);
                return o;
            }
        }
    }

    public class OverlayLayer
    {
        public byte[] Mask; public int W; public byte[] Colour;   // mask over the overlay area, RGB colour
    }

    public static class TextureOverlay
    {
        // Composites layers (drawn in order) onto the texture of a single-texture .ytd whose tile
        // covers overlay pixels [ox, ox + tw) x [oy, oy + th). Returns the new .ytd.
        public static byte[] Apply(byte[] ytd, List<OverlayLayer> layers, int ox, int oy)
        {
            var r = Rsc7.Read(ytd);
            byte[] s = r.Sys;
            int tp = (int)(BitConverter.ToUInt64(s, 0x30) & 0x0FFFFFFF);
            int t = (int)(BitConverter.ToUInt64(s, tp) & 0x0FFFFFFF);
            int w = BitConverter.ToUInt16(s, t + 0x50), h = BitConverter.ToUInt16(s, t + 0x52);
            uint fmt = BitConverter.ToUInt32(s, t + 0x58);
            int dataOff = (int)(BitConverter.ToUInt64(s, t + 0x70) & 0x0FFFFFFF);
            bool dxt5 = fmt == 0x35545844;
            if (!dxt5 && fmt != 0x31545844) throw new Exception("unsupported texture format");
            int bsz = dxt5 ? 16 : 8;
            int bw = w / 4;
            byte[] gfx = r.Gfx;
            var px = new byte[64];
            for (int by = 0; by < h / 4; by++)
            {
                for (int bx = 0; bx < bw; bx++)
                {
                    bool any = false;
                    foreach (var L in layers)
                    {
                        for (int yy = 0; yy < 4 && !any; yy++)
                        {
                            int row = (oy + by * 4 + yy) * L.W + ox + bx * 4;
                            for (int xx = 0; xx < 4; xx++) if (L.Mask[row + xx] != 0) { any = true; break; }
                        }
                        if (any) break;
                    }
                    if (!any) continue;
                    int bo = dataOff + (by * bw + bx) * bsz;
                    if (dxt5) { Dxt.DecodeColour(gfx, bo + 8, px, true); Dxt.DecodeAlpha(gfx, bo, px); }
                    else Dxt.DecodeColour(gfx, bo, px, false);
                    for (int i = 0; i < 16; i++)
                    {
                        int xx = i % 4, yy = i / 4;
                        double cr = px[4 * i], cg = px[4 * i + 1], cb = px[4 * i + 2];
                        int ca = px[4 * i + 3];
                        foreach (var L in layers)
                        {
                            int m = L.Mask[(oy + by * 4 + yy) * L.W + ox + bx * 4 + xx];
                            if (m == 0) continue;
                            double a = m / 255.0;
                            cr += (L.Colour[0] - cr) * a; cg += (L.Colour[1] - cg) * a; cb += (L.Colour[2] - cb) * a;
                            ca = Math.Max(ca, m);
                        }
                        px[4 * i] = (byte)Math.Round(cr); px[4 * i + 1] = (byte)Math.Round(cg); px[4 * i + 2] = (byte)Math.Round(cb);
                        px[4 * i + 3] = (byte)(dxt5 ? ca : 255);
                    }
                    if (dxt5) { Dxt.EncodeAlpha(px, gfx, bo); Dxt.EncodeColour(px, gfx, bo + 8); }
                    else Dxt.EncodeColour(px, gfx, bo);
                }
            }
            return Rsc7.Write(r);
        }
    }
}

