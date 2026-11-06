// Installs / removes the custom map.
//
//  * update\update.rpf  -> x64/data/cdimages/scaleform_generic.rpf: minimap_*.ytd textures
//    (pause map at far zoom, radar when zoomed out);
//  * x64e.rpf           -> levels/gta5/minimap.rpf: minimap_X_Y.ydd vector tiles
//    (pause map at close zoom and the radar), recoloured + hunting zones.
//
// For each archive (fully reversible, no OpenIV.asi needed):
//  * a copy of the nested archive with the new files appended is written to the end of the
//    top-level archive;
//  * the game only accepts encrypted TOCs, so all TOCs stay NG-encrypted: archive sizes are
//    padded so the NG key (hash(name) + size) stays the same, and only the changed 16-byte
//    TOC blocks are re-encrypted;
//  * the original TOC bytes + original file length are stored in a trailer at the end of the
//    file (and in <archive>.novamap.bak), so "restore" puts back the exact original bytes and
//    truncates the file.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace NovaMap
{
    public class Patcher
    {
        public class Target
        {
            public string File, TopName, Nested, Probe;
            public Target(string file, string top, string nested, string probe) { File = file; TopName = top; Nested = nested; Probe = probe; }
        }

        public static readonly Target Textures = new Target(@"update\update.rpf", "update.rpf", "x64/data/cdimages/scaleform_generic.rpf", "minimap_sea_0_0.ytd");
        public static readonly Target Vector = new Target("x64e.rpf", "x64e.rpf", "levels/gta5/minimap.rpf", "minimap_3_5.ydd");
        public const string NestedPath = "x64/data/cdimages/scaleform_generic.rpf";

        static readonly byte[] TrailerMagic = Encoding.ASCII.GetBytes("NOVAMAP1");

        public Action<string> Log = delegate { };

        public static string PathOf(string gtaDir, Target t) { return Path.Combine(gtaDir, t.File); }
        public static string UpdateRpf(string gtaDir) { return PathOf(gtaDir, Textures); }

        public class Trailer
        {
            public long OrigLength;
            public int HeaderLength;
            public long HeaderPos;
            public string Theme;
        }

        static long Align(long v, long a) { return (v + a - 1) / a * a; }

        public static Trailer ReadTrailer(Stream s)
        {
            if (s.Length < 1024) return null;
            s.Position = s.Length - 512;
            var b = new byte[512];
            s.Read(b, 0, 512);
            for (int i = 0; i < 8; i++) if (b[i] != TrailerMagic[i]) return null;
            var t = new Trailer();
            t.OrigLength = BitConverter.ToInt64(b, 8);
            t.HeaderLength = BitConverter.ToInt32(b, 16);
            t.HeaderPos = BitConverter.ToInt64(b, 20);
            int tl = b[28];
            t.Theme = Encoding.UTF8.GetString(b, 29, tl);
            return t;
        }

        static byte[] BuildTrailer(Trailer t)
        {
            var b = new byte[512];
            Buffer.BlockCopy(TrailerMagic, 0, b, 0, 8);
            Buffer.BlockCopy(BitConverter.GetBytes(t.OrigLength), 0, b, 8, 8);
            Buffer.BlockCopy(BitConverter.GetBytes(t.HeaderLength), 0, b, 16, 4);
            Buffer.BlockCopy(BitConverter.GetBytes(t.HeaderPos), 0, b, 20, 8);
            var tb = Encoding.UTF8.GetBytes(t.Theme ?? "");
            b[28] = (byte)tb.Length;
            Buffer.BlockCopy(tb, 0, b, 29, tb.Length);
            return b;
        }

        public string InstalledTheme(string gtaDir)
        {
            using (var s = new FileStream(UpdateRpf(gtaDir), FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                var t = ReadTrailer(s);
                return t == null ? null : t.Theme;
            }
        }

        static void ReadFull(Stream s, byte[] buf)
        {
            int got = 0;
            while (got < buf.Length)
            {
                int n = s.Read(buf, got, buf.Length - got);
                if (n <= 0) throw new EndOfStreamException();
                got += n;
            }
        }

        static bool Same(byte[] a, byte[] b)
        {
            if (a.Length != b.Length) return false;
            for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
            return true;
        }

        // ------------------------------------------------------------------ restore

        // Puts back the original TOC and truncates the appended data. Returns false if nothing installed.
        public bool RestoreArchive(string path)
        {
            if (!File.Exists(path)) return false;
            using (var s = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                var t = ReadTrailer(s);
                if (t == null) return false;
                if (t.OrigLength <= 0 || t.OrigLength > s.Length || t.HeaderPos < t.OrigLength)
                    throw new Exception("Повреждённые данные установки в " + Path.GetFileName(path) + ", восстановление невозможно. Проверьте целостность файлов игры.");
                var hdr = new byte[t.HeaderLength];
                s.Position = t.HeaderPos;
                ReadFull(s, hdr);
                if (BitConverter.ToUInt32(hdr, 0) != 0x52504637) throw new Exception("Резервная копия заголовка повреждена.");
                s.Position = 0;
                s.Write(hdr, 0, hdr.Length);
                s.SetLength(t.OrigLength);
                s.Flush(true);
            }
            try { File.Delete(path + ".novamap.bak"); } catch { }
            Log("Восстановлен " + Path.GetFileName(path));
            return true;
        }

        // Restores from <archive>.novamap.bak when the trailer is gone/damaged.
        public bool RestoreArchiveFromBackup(string path)
        {
            string bak = path + ".novamap.bak";
            if (!File.Exists(bak) || !File.Exists(path)) return false;
            byte[] b = File.ReadAllBytes(bak);
            for (int i = 0; i < 8; i++) if (b[i] != TrailerMagic[i]) return false;
            long origLength = BitConverter.ToInt64(b, 8);
            int hl = BitConverter.ToInt32(b, 16);
            using (var s = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                if (s.Length <= origLength) return false;   // nothing appended -> nothing to undo
                // only valid for the same archive build: version, entry count and names length must match
                var cur = new byte[12];
                s.Position = 0;
                ReadFull(s, cur);
                for (int i = 0; i < 12; i++) if (cur[i] != b[20 + i]) return false;
                s.Position = 0;
                s.Write(b, 20, hl);
                s.SetLength(origLength);
                s.Flush(true);
            }
            File.Delete(bak);
            Log("Восстановлен " + Path.GetFileName(path) + " (из резервной копии)");
            return true;
        }

        // Undo everything; returns false if nothing was installed.
        public bool RestoreAll(string gtaDir)
        {
            bool any = false;
            foreach (var t in new[] { Textures, Vector })
            {
                string p = PathOf(gtaDir, t);
                if (RestoreArchive(p) || RestoreArchiveFromBackup(p)) any = true;
            }
            if (UnhideLegacyTiles(gtaDir)) any = true;
            return any;
        }

        // ------------------------------------------------------------------ install

        // texFiles: minimap_*.ytd for update.rpf. vecBuilder gets the player's vanilla vector tiles
        // (minimap_X_Y.ydd, read after the previous install was removed) and returns the new ones.
        public void Install(string gtaDir, string theme, Dictionary<string, byte[]> texFiles,
                            Func<Dictionary<string, byte[]>, Dictionary<string, byte[]>> vecBuilder)
        {
            if (RestoreAll(gtaDir)) Log("Предыдущая установка снята.");
            PatchArchive(gtaDir, Textures, theme, texFiles, "Записываю текстуры карты (update.rpf)...");
            Log("Собираю векторную карту...");
            var vec = vecBuilder(ReadVanillaVectorTiles(gtaDir));
            PatchArchive(gtaDir, Vector, theme, vec, "Записываю векторную карту (x64e.rpf)...");
            Log("Готово!");
        }

        public static Dictionary<string, byte[]> ReadVanillaVectorTiles(string gtaDir)
        {
            var outp = new Dictionary<string, byte[]>();
            using (var s = new FileStream(PathOf(gtaDir, Vector), FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                var top = RpfArchive.Open(s, 0, s.Length, Vector.TopName, Vector.TopName);
                var ne = top.Find(Vector.Nested);
                if (ne == null) throw new Exception("В x64e.rpf не найден " + Vector.Nested);
                var nested = top.OpenChild(s, ne);
                foreach (var e in nested.Entries)
                    if (e.IsResource && IsTile(e.Name, "minimap_")) outp[e.Name] = nested.ExtractResourceFile(s, e);
            }
            if (outp.Count == 0) throw new Exception("В x64e.rpf нет векторных тайлов карты");
            return outp;
        }

        void PatchArchive(string gtaDir, Target t, string theme, Dictionary<string, byte[]> files, string msg)
        {
            string path = PathOf(gtaDir, t);
            if (!File.Exists(path)) throw new Exception("Не найден файл " + path);
            Log(msg);
            using (var s = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                long origLength = s.Length;
                var top = RpfArchive.Open(s, 0, s.Length, t.TopName, t.TopName);
                int headerLength = top.HeaderLength;
                var origHeader = new byte[headerLength];
                s.Position = 0;
                ReadFull(s, origHeader);

                var entry = top.Find(t.Nested);
                if (entry == null || !entry.IsBinary) throw new Exception("В " + t.TopName + " не найден " + t.Nested);
                var nested = top.OpenChild(s, entry);

                var replace = new Dictionary<string, byte[]>();
                foreach (var kv in files)
                {
                    var e = nested.Find(kv.Key);
                    if (e == null || !e.IsResource) throw new Exception("В архиве нет файла " + kv.Key);
                    replace[e.Path.ToLowerInvariant()] = kv.Value;
                }
                byte[] newNested = nested.AppendReplace(s, replace);

                // self-check: the new archive must decrypt with the key of its new size
                using (var ms = new MemoryStream(newNested))
                {
                    var chk = RpfArchive.Open(ms, 0, ms.Length, entry.Name, entry.Name);
                    if (chk.EntryCount != nested.EntryCount || chk.Encryption != nested.Encryption)
                        throw new Exception("Проверка архива не пройдена (entries).");
                    for (int i = 0; i < chk.Entries.Count; i++)
                        if (chk.Entries[i].Path != nested.Entries[i].Path) throw new Exception("Проверка архива не пройдена (names).");
                    foreach (var kv in files)
                    {
                        var e = chk.Find(kv.Key);
                        if (!Same(chk.ReadStored(ms, e), kv.Value)) throw new Exception("Проверка архива не пройдена: " + kv.Key);
                    }
                }

                File.WriteAllBytes(path + ".novamap.bak", BuildBackupFile(origLength, origHeader));

                // layout: [original][new nested archive][copy of original TOC][...][trailer]
                long nestedPos = Align(origLength, 512);
                long headerPos = Align(nestedPos + newNested.Length, 512);
                long finalSize = top.SizeKeepingKey(headerPos + headerLength + 512);
                long trailerPos = finalSize - 512;
                if (nestedPos / 512 > 0xFFFFFF || finalSize > uint.MaxValue) throw new Exception(t.TopName + " слишком большой для установки.");

                entry.FileOffset = (uint)(nestedPos / 512);
                entry.FileSize = 0;
                entry.UncompressedSize = (uint)newNested.Length;
                byte[] entryBlock = top.EncryptEntry(entry, (uint)finalSize);

                s.SetLength(finalSize);
                s.Position = nestedPos;
                s.Write(newNested, 0, newNested.Length);
                s.Position = headerPos;
                s.Write(origHeader, 0, origHeader.Length);
                var tr = new Trailer();
                tr.OrigLength = origLength; tr.HeaderLength = headerLength; tr.HeaderPos = headerPos; tr.Theme = theme;
                s.Position = trailerPos;
                var tb = BuildTrailer(tr);
                s.Write(tb, 0, tb.Length);
                s.Position = 16 + entry.Index * 16;
                s.Write(entryBlock, 0, 16);
                s.Flush(true);
            }
            VerifyArchive(gtaDir, t, files);
        }

        static byte[] BuildBackupFile(long origLength, byte[] header)
        {
            using (var ms = new MemoryStream())
            {
                var w = new BinaryWriter(ms);
                w.Write(TrailerMagic);
                w.Write(origLength);
                w.Write(header.Length);
                w.Write(header);
                return ms.ToArray();
            }
        }

        public static void VerifyArchive(string gtaDir, Target t, Dictionary<string, byte[]> files)
        {
            using (var s = new FileStream(PathOf(gtaDir, t), FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                var top = RpfArchive.Open(s, 0, s.Length, t.TopName, t.TopName);
                var ne = top.Find(t.Nested);
                if (ne == null) throw new Exception("Проверка после записи не пройдена: оглавление " + t.TopName + " не читается.");
                var nested = top.OpenChild(s, ne);
                if (nested.Find(t.Probe) == null) throw new Exception("Проверка после записи не пройдена: оглавление карты не читается.");
                foreach (var kv in files)
                {
                    var e = nested.Find(kv.Key);
                    if (e == null || !Same(nested.ReadStored(s, e), kv.Value))
                        throw new Exception("Проверка после записи не пройдена: " + kv.Key);
                }
            }
        }

        // ------------------------------------------------------------------ legacy cleanup
        // Version 2 of this installer hid the vector tiles by renaming them minimap_ -> minimaq_
        // in x64e.rpf (names table only). Undo that if present.
        static bool IsTile(string name, string prefix)
        {
            if (!name.StartsWith(prefix) || !name.EndsWith(".ydd")) return false;
            var mid = name.Substring(prefix.Length, name.Length - prefix.Length - 4).Split('_');
            int a, b;
            return mid.Length == 2 && int.TryParse(mid[0], out a) && int.TryParse(mid[1], out b);
        }

        public bool UnhideLegacyTiles(string gtaDir)
        {
            string path = PathOf(gtaDir, Vector);
            if (!File.Exists(path)) return false;
            using (var s = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                var top = RpfArchive.Open(s, 0, s.Length, Vector.TopName, Vector.TopName);
                var e = top.Find(Vector.Nested);
                if (e == null) return false;
                var nested = top.OpenChild(s, e);
                var plain = nested.NamesData;
                var target = (byte[])plain.Clone();
                int n = 0;
                foreach (var f in nested.Entries)
                {
                    if (f.IsDir || !IsTile(f.Name, "minimaq_")) continue;
                    var tb = Encoding.ASCII.GetBytes("minimap_");
                    Buffer.BlockCopy(tb, 0, target, (int)f.NameOffset, tb.Length);
                    n++;
                }
                if (n == 0) return false;
                Log("Возвращаю ванильные векторные тайлы (после прошлой версии)...");
                for (int b = 0; b < target.Length / 16; b++)
                {
                    bool diff = false;
                    for (int i = b * 16; i < b * 16 + 16; i++) if (target[i] != plain[i]) { diff = true; break; }
                    if (!diff) continue;
                    var pb = new byte[16];
                    Buffer.BlockCopy(target, b * 16, pb, 0, 16);
                    var enc = nested.EncryptTocBlock(pb, (uint)nested.Size);
                    s.Position = nested.NamesPos + b * 16;
                    s.Write(enc, 0, 16);
                }
                s.Flush(true);
            }
            return true;
        }
    }
}
