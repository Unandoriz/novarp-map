// Developer CLI over NovaRpf: list / find / extract files from GTA V archives.
using System;
using System.Collections.Generic;
using System.IO;

namespace NovaMap
{
    static class RpfTool
    {
        static void LoadKeys(string keyFile, string magicFile)
        {
            GtaKeys.Load(File.ReadAllBytes(keyFile), File.ReadAllBytes(magicFile));
        }

        // Resolves "a/b/c.rpf/d/e.ytd" inside a top-level archive; returns archive holding the last part.
        static RpfArchive Resolve(Stream s, RpfArchive top, string inner, out string rest)
        {
            var arc = top;
            var parts = inner.Replace('\\', '/').Split('/');
            string cur = "";
            for (int i = 0; i < parts.Length; i++)
            {
                cur = cur.Length == 0 ? parts[i] : cur + "/" + parts[i];
                if (parts[i].ToLowerInvariant().EndsWith(".rpf") && i < parts.Length - 1)
                {
                    var e = arc.Find(cur);
                    if (e == null) throw new Exception("Not found: " + cur);
                    arc = arc.OpenChild(s, e);
                    cur = "";
                }
            }
            rest = cur;
            return arc;
        }

        static void List(Stream s, RpfArchive a, string filter, bool recurse)
        {
            foreach (var e in a.Entries)
            {
                if (e.IsDir) continue;
                string full = a.Path + "/" + e.Path;
                if (filter == null || full.ToLowerInvariant().Contains(filter))
                    Console.WriteLine("{0}\t{1}\t{2}\t{3}", e.IsResource ? "RES" : (e.IsEncrypted ? "BIN*" : "BIN"), e.StoredSize, a.Encryption, full);
                if (recurse && e.IsBinary && e.Name.ToLowerInvariant().EndsWith(".rpf"))
                {
                    try { List(s, a.OpenChild(s, e), filter, true); }
                    catch (Exception ex) { Console.Error.WriteLine("ERR " + full + ": " + ex.Message); }
                }
            }
        }

        static void CompareRec(Stream sa, RpfArchive a, Stream sb, RpfArchive b, ref int same, ref int diff)
        {
            // entries are matched by path: a modded archive may have more (or fewer) entries
            var byPath = new Dictionary<string, RpfEntry>();
            foreach (var ea in a.Entries) byPath[ea.Path.ToLowerInvariant()] = ea;
            var seen = new HashSet<string>();
            foreach (var eb in b.Entries)
            {
                string key = eb.Path.ToLowerInvariant();
                seen.Add(key);
                RpfEntry ea;
                if (!byPath.TryGetValue(key, out ea))
                {
                    diff++;
                    Console.WriteLine("ADDED {0}/{1} ({2} bytes)", b.Path, eb.Path, eb.IsDir ? 0 : eb.UncompressedSize);
                    continue;
                }
                if (eb.IsDir) continue;
                if (eb.IsBinary && eb.Name.ToLowerInvariant().EndsWith(".rpf") && ea.IsBinary)
                {
                    CompareRec(sa, a.OpenChild(sa, ea), sb, b.OpenChild(sb, eb), ref same, ref diff);
                    continue;
                }
                byte[] da = ea.IsResource ? a.ExtractResourceFile(sa, ea) : a.ExtractBinary(sa, ea);
                byte[] db = eb.IsResource ? b.ExtractResourceFile(sb, eb) : b.ExtractBinary(sb, eb);
                bool eq = da.Length == db.Length;
                if (eq) for (int k = 0; k < da.Length; k++) if (da[k] != db[k]) { eq = false; break; }
                if (eq) same++;
                else { diff++; Console.WriteLine("DIFF {0}/{1} ({2} -> {3} bytes)", b.Path, eb.Path, da.Length, db.Length); }
            }
            foreach (var ea in a.Entries)
                if (!seen.Contains(ea.Path.ToLowerInvariant())) { diff++; Console.WriteLine("REMOVED {0}/{1}", a.Path, ea.Path); }
        }

        static int DiffBlocks(byte[] x, byte[] y)
        {
            int n = 0;
            for (int i = 0; i < x.Length; i += 16)
                for (int j = i; j < i + 16 && j < x.Length; j++) if (x[j] != y[j]) { n++; break; }
            return n;
        }

        static void EncScan(Stream s, RpfArchive a, Dictionary<string, int> counts)
        {
            string k = a.Encryption.ToString() + (a.Parent == null ? " (top)" : " (nested)");
            int c; counts.TryGetValue(k, out c); counts[k] = c + 1;
            if (a.Encryption != RpfEnc.NG) Console.WriteLine("{0}\t{1}", a.Encryption, a.Path);
            foreach (var e in a.Entries)
            {
                if (e.IsBinary && e.Name.ToLowerInvariant().EndsWith(".rpf"))
                {
                    try { EncScan(s, a.OpenChild(s, e), counts); }
                    catch (Exception ex) { Console.WriteLine("ERR " + a.Path + "/" + e.Path + " " + ex.Message); }
                }
            }
        }

        static int Main(string[] args)
        {
            try
            {
                string cmd = args[0];
                if (cmd == "keys")
                {
                    var key = GtaKeys.FindAesKey(File.ReadAllBytes(Path.Combine(args[1], "GTA5.exe")));
                    if (key == null) { Console.WriteLine("key not found"); return 1; }
                    File.WriteAllBytes(args[2], key);
                    Console.WriteLine("ok");
                    return 0;
                }
                LoadKeys(args[1], args[2]);
                if (cmd == "list")
                {
                    // list key magic rpf [filter]
                    using (var s = File.OpenRead(args[3]))
                    {
                        var a = RpfArchive.Open(s, 0, s.Length, Path.GetFileName(args[3]), Path.GetFileName(args[3]));
                        List(s, a, args.Length > 4 ? args[4].ToLowerInvariant() : null, true);
                    }
                }
                else if (cmd == "extract")
                {
                    // extract key magic rpf innerpath outfile
                    using (var s = File.OpenRead(args[3]))
                    {
                        var top = RpfArchive.Open(s, 0, s.Length, Path.GetFileName(args[3]), Path.GetFileName(args[3]));
                        string rest;
                        var a = Resolve(s, top, args[4], out rest);
                        var e = a.Find(rest);
                        if (e == null) throw new Exception("Not found: " + rest);
                        byte[] d = e.IsResource ? a.ExtractResourceFile(s, e) : a.ExtractBinary(s, e);
                        File.WriteAllBytes(args[5], d);
                        Console.WriteLine("{0} bytes -> {1}", d.Length, args[5]);
                    }
                }
                else if (cmd == "install")
                {
                    // install key magic gtaDir theme ytdDir yddDir
                    var files = new Dictionary<string, byte[]>();
                    foreach (var f in Directory.GetFiles(args[5], "*.ytd")) files[Path.GetFileName(f)] = File.ReadAllBytes(f);
                    var vec = new Dictionary<string, byte[]>();
                    foreach (var f in Directory.GetFiles(args[6], "*.ydd")) vec[Path.GetFileName(f)] = File.ReadAllBytes(f);
                    var p = new Patcher();
                    p.Log = Console.WriteLine;
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    p.Install(args[3], args[4], files, delegate (Dictionary<string, byte[]> van) { return vec; });
                    Console.WriteLine("installed in {0} ms", sw.ElapsedMilliseconds);
                }
                else if (cmd == "restore")
                {
                    var p = new Patcher();
                    p.Log = Console.WriteLine;
                    bool ok = p.RestoreAll(args[3]);
                    Console.WriteLine("restore: " + ok);
                }
                else if (cmd == "compare")
                {
                    // compare key magic origRpf patchedRpf [origName [patchedName]] : every file in every nested archive
                    // must extract identically (names matter: the NG key depends on the archive's in-game name)
                    using (var a = File.OpenRead(args[3]))
                    using (var b = File.OpenRead(args[4]))
                    {
                        string na = args.Length > 5 ? args[5] : Path.GetFileName(args[3]), nb = args.Length > 6 ? args[6] : Path.GetFileName(args[4]);
                        var ta = RpfArchive.Open(a, 0, a.Length, na, na);
                        var tb = RpfArchive.Open(b, 0, b.Length, nb, nb);
                        int same = 0, diff = 0;
                        CompareRec(a, ta, b, tb, ref same, ref diff);
                        Console.WriteLine("same={0} diff={1} enc {2}->{3}", same, diff, ta.Encryption, tb.Encryption);
                    }
                }
                else if (cmd == "vectest")
                {
                    // vectest key magic plan theme grid labels expectedDir vanillaDir
                    var plan = VectorPlan.Load(File.ReadAllBytes(args[3]));
                    int ti = plan.ThemeIndex(args[4]);
                    bool grid = args[5] == "1", labels = args[6] == "1";
                    int same = 0, diff = 0;
                    foreach (var f in Directory.GetFiles(args[7], "*.sys"))
                    {
                        string name = Path.GetFileNameWithoutExtension(f);
                        var exp = File.ReadAllBytes(f);
                        var van = Rsc7.Read(File.ReadAllBytes(Path.Combine(args[8], name)));
                        var res = plan.Apply(van, name, ti, grid, labels);
                        var got = new byte[res.Sys.Length + 4];
                        Buffer.BlockCopy(res.Sys, 0, got, 0, res.Sys.Length);
                        Buffer.BlockCopy(BitConverter.GetBytes(res.SysFlags), 0, got, res.Sys.Length, 4);
                        bool eq = got.Length == exp.Length;
                        int firstDiff = -1;
                        if (eq) for (int i = 0; i < got.Length; i++) if (got[i] != exp[i]) { eq = false; firstDiff = i; break; }
                        if (eq) same++;
                        else { diff++; Console.WriteLine("DIFF {0} len {1}/{2} first@{3}", name, got.Length, exp.Length, firstDiff); }
                        // also make sure it round-trips through RSC7
                        Rsc7.Read(Rsc7.Write(res));
                    }
                    Console.WriteLine("vector tiles identical: {0}, different: {1}", same, diff);
                }
                else if (cmd == "vecinstalled")
                {
                    // vecinstalled key magic x64eRpf expectedDir : installed vector tiles vs Python reference
                    int same = 0, diff = 0;
                    using (var s = File.OpenRead(args[3]))
                    {
                        var top = RpfArchive.Open(s, 0, s.Length, "x64e.rpf", "x64e.rpf");
                        string rest;
                        var a = Resolve(s, top, "levels/gta5/minimap.rpf/x", out rest);
                        foreach (var f in Directory.GetFiles(args[4], "*.sys"))
                        {
                            string name = Path.GetFileNameWithoutExtension(f);
                            var res = Rsc7.Read(a.ExtractResourceFile(s, a.Find(name)));
                            var got = new byte[res.Sys.Length + 4];
                            Buffer.BlockCopy(res.Sys, 0, got, 0, res.Sys.Length);
                            Buffer.BlockCopy(BitConverter.GetBytes(res.SysFlags), 0, got, res.Sys.Length, 4);
                            var exp = File.ReadAllBytes(f);
                            bool eq = got.Length == exp.Length;
                            if (eq) for (int i = 0; i < got.Length; i++) if (got[i] != exp[i]) { eq = false; break; }
                            if (eq) same++; else { diff++; Console.WriteLine("DIFF " + name); }
                        }
                    }
                    Console.WriteLine("installed vector tiles identical: {0}, different: {1}", same, diff);
                }
                else if (cmd == "texapply")
                {
                    // texapply key magic plan theme ytdIn ytdOut ox oy labelsPng|- gridPng|-
                    var plan = VectorPlan.Load(File.ReadAllBytes(args[3]));
                    var th = plan.Themes[plan.ThemeIndex(args[4])];
                    var layers = new List<OverlayLayer>();
                    if (args[10] != "-")
                    {
                        var g = Overlay.FromPng(File.ReadAllBytes(args[10]));
                        layers.Add(new OverlayLayer { Mask = g.C1, W = g.W, Colour = th.OverlayColours[4] });
                        layers.Add(new OverlayLayer { Mask = g.C0, W = g.W, Colour = th.OverlayColours[3] });
                    }
                    if (args[9] != "-")
                    {
                        var o = Overlay.FromPng(File.ReadAllBytes(args[9]));
                        layers.Add(new OverlayLayer { Mask = o.C1, W = o.W, Colour = th.OverlayColours[1] });
                        layers.Add(new OverlayLayer { Mask = o.C0, W = o.W, Colour = th.OverlayColours[0] });
                        layers.Add(new OverlayLayer { Mask = o.C2, W = o.W, Colour = th.OverlayColours[2] });
                    }
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    var outp = TextureOverlay.Apply(File.ReadAllBytes(args[5]), layers, int.Parse(args[7]), int.Parse(args[8]));
                    File.WriteAllBytes(args[6], outp);
                    Console.WriteLine("texture composed in {0} ms", sw.ElapsedMilliseconds);
                }
                else if (cmd == "encscan")
                {
                    // encscan key magic gtaDir : encryption type of every (nested) archive
                    var counts = new Dictionary<string, int>();
                    foreach (var f in Directory.GetFiles(args[3], "*.rpf", SearchOption.AllDirectories))
                    {
                        try
                        {
                            using (var s = File.OpenRead(f))
                            {
                                var a = RpfArchive.Open(s, 0, s.Length, Path.GetFileName(f), f.Substring(args[3].Length));
                                EncScan(s, a, counts);
                            }
                        }
                        catch (Exception ex) { Console.WriteLine("ERR " + f + " " + ex.Message); }
                    }
                    foreach (var kv in counts) Console.WriteLine("{0}\t{1}", kv.Key, kv.Value);
                }
                else if (cmd == "tocdiff")
                {
                    // tocdiff key magic origRpf patchedRpf : raw (encrypted) TOC blocks that differ, top + scaleform_generic
                    using (var a = File.OpenRead(args[3]))
                    using (var b = File.OpenRead(args[4]))
                    {
                        var ta = RpfArchive.Open(a, 0, a.Length, Path.GetFileName(args[3]), Path.GetFileName(args[3]));
                        var tb = RpfArchive.Open(b, 0, b.Length, Path.GetFileName(args[4]), Path.GetFileName(args[4]));
                        Console.WriteLine("top: {0} of {1} entry blocks differ, names same: {2}", DiffBlocks(ta.RawEntries, tb.RawEntries), ta.EntryCount, DiffBlocks(ta.RawNames, tb.RawNames) == 0);
                        var na = ta.OpenChild(a, ta.Find(Patcher.NestedPath));
                        var nb = tb.OpenChild(b, tb.Find(Patcher.NestedPath));
                        Console.WriteLine("nested: {0} of {1} entry blocks differ, names same: {2}, size {3} -> {4}", DiffBlocks(na.RawEntries, nb.RawEntries), na.EntryCount, DiffBlocks(na.RawNames, nb.RawNames) == 0, na.Size, nb.Size);
                    }
                }
                else if (cmd == "space")
                {
                    // space key magic rpf innerArchivePath : used vs allocated bytes, encrypted binaries
                    using (var s = File.OpenRead(args[3]))
                    {
                        var top = RpfArchive.Open(s, 0, s.Length, Path.GetFileName(args[3]), Path.GetFileName(args[3]));
                        string rest;
                        var a = RpfTool.Resolve(s, top, args[4] + "/x", out rest);
                        long used = (a.HeaderLength + 511) / 512 * 512;
                        long maxEnd = 0;
                        int encBin = 0, plainBin = 0, res = 0;
                        foreach (var e in a.Entries)
                        {
                            if (e.IsDir) continue;
                            used += (e.StoredSize + 511) / 512 * 512;
                            maxEnd = Math.Max(maxEnd, (long)e.FileOffset * 512 + e.StoredSize);
                            if (e.IsResource) res++; else if (e.IsEncrypted) encBin++; else plainBin++;
                        }
                        Console.WriteLine("{0}: enc={1} size={2} used={3} free={4} lastEnd={5} res={6} encBin={7} plainBin={8}",
                            a.Path, a.Encryption, a.Size, used, a.Size - used, maxEnd, res, encBin, plainBin);
                    }
                }
                else if (cmd == "header")
                {
                    // header key magic rpf innerArchivePath : print archive info
                    using (var s = File.OpenRead(args[3]))
                    {
                        var top = RpfArchive.Open(s, 0, s.Length, Path.GetFileName(args[3]), Path.GetFileName(args[3]));
                        var a = top;
                        if (args.Length > 4)
                        {
                            string rest;
                            a = Resolve(s, top, args[4] + "/x", out rest);
                        }
                        Console.WriteLine("{0} start={1} size={2} entries={3} names={4} enc={5}", a.Path, a.StartPos, a.Size, a.EntryCount, a.NamesLength, a.Encryption);
                        if (a.ParentEntry != null)
                            Console.WriteLine("parent entry: off={0} fs={1} us={2} enc={3}", a.ParentEntry.FileOffset, a.ParentEntry.FileSize, a.ParentEntry.UncompressedSize, a.ParentEntry.IsEncrypted);
                    }
                }
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex.ToString());
                return 2;
            }
        }
    }
}

