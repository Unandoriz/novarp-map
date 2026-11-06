// RPF7 (GTA V) archive reading / patching.
// Crypto ported from CodeWalker (GTACrypto.cs, GTAKeys.cs: MIT, (c) Neodymium); archive handling
// follows its RpfFile.cs ((c) dexyfex). See THIRD_PARTY_NOTICES.md.
// Written for the C# 5 compiler that ships with .NET Framework 4.x (csc.exe).
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;

namespace NovaMap
{
    public static class GtaKeys
    {
        static readonly byte[] AesKeyHash = new byte[] { 0xA0, 0x79, 0x61, 0x28, 0xA7, 0x75, 0x72, 0x0A, 0xC2, 0x04, 0xD9, 0x81, 0x9F, 0x68, 0xC1, 0x72, 0xE3, 0x95, 0x2C, 0x6D };

        public static byte[] AesKey;
        public static byte[][] NgKeys;        // 101 x 272
        public static uint[][][] NgTables;    // 17 x 16 x 256
        public static byte[] Lut;             // 256
        public static bool Loaded;

        public static byte[] FindAesKey(byte[] exe)
        {
            const int BLOCK = 1 << 20;
            byte[] found = null;
            int blocks = (exe.Length + BLOCK - 1) / BLOCK;
            Parallel.For(0, blocks, delegate (int k, ParallelLoopState state)
            {
                using (var sha = new SHA1CryptoServiceProvider())
                {
                    int end = Math.Min(exe.Length - 32, (k + 1) * BLOCK);
                    for (int p = k * BLOCK; p < end; p += 8)
                    {
                        if (found != null) return;
                        byte[] h = sha.ComputeHash(exe, p, 32);
                        bool eq = true;
                        for (int i = 0; i < 20; i++) { if (h[i] != AesKeyHash[i]) { eq = false; break; } }
                        if (eq)
                        {
                            byte[] key = new byte[32];
                            Buffer.BlockCopy(exe, p, key, 0, 32);
                            found = key;
                            state.Stop();
                            return;
                        }
                    }
                }
            });
            return found;
        }

        static uint JenkBytes(byte[] data)
        {
            uint h = 0;
            for (int i = 0; i < data.Length; i++)
            {
                h += data[i];
                h += (h << 10);
                h ^= (h >> 6);
            }
            h += (h << 3);
            h ^= (h >> 11);
            h += (h << 15);
            return h;
        }

        public static void Load(byte[] aesKey, byte[] magic)
        {
            AesKey = aesKey;
            var rnd = new Random((int)JenkBytes(aesKey));
            int n = magic.Length;
            var r1 = new byte[n]; var r2 = new byte[n]; var r3 = new byte[n]; var r4 = new byte[n];
            rnd.NextBytes(r1); rnd.NextBytes(r2); rnd.NextBytes(r3); rnd.NextBytes(r4);
            var db = new byte[n];
            for (int i = 0; i < n; i++) db[i] = (byte)((magic[i] - r1[i] - r2[i] - r3[i] - r4[i]) & 0xFF);
            db = Crypto.DecryptAes(db, aesKey);
            byte[] b;
            using (var ms = new MemoryStream(db))
            using (var ds = new DeflateStream(ms, CompressionMode.Decompress))
            using (var outs = new MemoryStream())
            {
                ds.CopyTo(outs);
                b = outs.ToArray();
            }
            int bp = 0;
            NgKeys = new byte[101][];
            for (int i = 0; i < 101; i++) { NgKeys[i] = new byte[272]; Buffer.BlockCopy(b, bp, NgKeys[i], 0, 272); bp += 272; }
            NgTables = new uint[17][][];
            for (int i = 0; i < 17; i++)
            {
                NgTables[i] = new uint[16][];
                for (int j = 0; j < 16; j++)
                {
                    NgTables[i][j] = new uint[256];
                    Buffer.BlockCopy(b, bp, NgTables[i][j], 0, 1024); bp += 1024;
                }
            }
            Lut = new byte[256];
            Buffer.BlockCopy(b, bp, Lut, 0, 256);
            Loaded = true;
        }

        public static void LoadFromGame(string gtaDir, byte[] magic)
        {
            string exe = Path.Combine(gtaDir, "GTA5.exe");
            byte[] key = FindAesKey(File.ReadAllBytes(exe));
            if (key == null) throw new Exception("Не удалось найти ключ в GTA5.exe (неподдерживаемая версия игры?)");
            Load(key, magic);
        }
    }

    public static class Crypto
    {
        public static byte[] DecryptAes(byte[] data, byte[] key)
        {
            var r = Rijndael.Create();
            r.KeySize = 256; r.Key = key; r.BlockSize = 128; r.Mode = CipherMode.ECB; r.Padding = PaddingMode.None;
            var buf = (byte[])data.Clone();
            int len = data.Length - data.Length % 16;
            if (len > 0) r.CreateDecryptor().TransformBlock(buf, 0, len, buf, 0);
            return buf;
        }

        public static uint Gta5Hash(string text)
        {
            uint result = 0;
            for (int i = 0; i < text.Length; i++)
            {
                uint temp = 1025 * (GtaKeys.Lut[text[i] & 0xFF] + result);
                result = (temp >> 6) ^ temp;
            }
            return 32769 * ((9 * result >> 11) ^ (9 * result));
        }

        public static uint NgKeyIndex(string name, uint length)
        {
            uint hash = Gta5Hash(name);
            return (hash + length + (101 - 40)) % 0x65;
        }

        public static byte[] GetNgKey(string name, uint length)
        {
            return GtaKeys.NgKeys[NgKeyIndex(name, length)];
        }

        public static byte[] EncryptAesBlock(byte[] data, byte[] key)
        {
            var r = Rijndael.Create();
            r.KeySize = 256; r.Key = key; r.BlockSize = 128; r.Mode = CipherMode.ECB; r.Padding = PaddingMode.None;
            var buf = (byte[])data.Clone();
            r.CreateEncryptor().TransformBlock(buf, 0, 16, buf, 0);
            return buf;
        }

        public static byte[] DecryptNg(byte[] data, string name, uint length)
        {
            return DecryptNg(data, GetNgKey(name, length));
        }

        public static byte[] DecryptNg(byte[] data, byte[] key)
        {
            var k = new uint[68];
            Buffer.BlockCopy(key, 0, k, 0, 272);
            var outp = (byte[])data.Clone();
            var t = GtaKeys.NgTables;
            var blk = new byte[16];
            for (int b = 0; b + 16 <= data.Length; b += 16)
            {
                Buffer.BlockCopy(data, b, blk, 0, 16);
                RoundA(blk, k, 0, t[0]);
                RoundA(blk, k, 1, t[1]);
                for (int r = 2; r <= 15; r++) RoundB(blk, k, r, t[r]);
                RoundA(blk, k, 16, t[16]);
                Buffer.BlockCopy(blk, 0, outp, b, 16);
            }
            return outp;
        }

        static void Put(byte[] d, int o, uint v)
        {
            d[o] = (byte)v; d[o + 1] = (byte)(v >> 8); d[o + 2] = (byte)(v >> 16); d[o + 3] = (byte)(v >> 24);
        }

        static void RoundA(byte[] d, uint[] k, int r, uint[][] t)
        {
            uint x1 = t[0][d[0]] ^ t[1][d[1]] ^ t[2][d[2]] ^ t[3][d[3]] ^ k[4 * r + 0];
            uint x2 = t[4][d[4]] ^ t[5][d[5]] ^ t[6][d[6]] ^ t[7][d[7]] ^ k[4 * r + 1];
            uint x3 = t[8][d[8]] ^ t[9][d[9]] ^ t[10][d[10]] ^ t[11][d[11]] ^ k[4 * r + 2];
            uint x4 = t[12][d[12]] ^ t[13][d[13]] ^ t[14][d[14]] ^ t[15][d[15]] ^ k[4 * r + 3];
            Put(d, 0, x1); Put(d, 4, x2); Put(d, 8, x3); Put(d, 12, x4);
        }

        static void RoundB(byte[] d, uint[] k, int r, uint[][] t)
        {
            uint x1 = t[0][d[0]] ^ t[7][d[7]] ^ t[10][d[10]] ^ t[13][d[13]] ^ k[4 * r + 0];
            uint x2 = t[1][d[1]] ^ t[4][d[4]] ^ t[11][d[11]] ^ t[14][d[14]] ^ k[4 * r + 1];
            uint x3 = t[2][d[2]] ^ t[5][d[5]] ^ t[8][d[8]] ^ t[15][d[15]] ^ k[4 * r + 2];
            uint x4 = t[3][d[3]] ^ t[6][d[6]] ^ t[9][d[9]] ^ t[12][d[12]] ^ k[4 * r + 3];
            Put(d, 0, x1); Put(d, 4, x2); Put(d, 8, x3); Put(d, 12, x4);
        }

        public static byte[] Inflate(byte[] data, int offset)
        {
            using (var ms = new MemoryStream(data, offset, data.Length - offset))
            using (var ds = new DeflateStream(ms, CompressionMode.Decompress))
            using (var outs = new MemoryStream())
            {
                ds.CopyTo(outs);
                return outs.ToArray();
            }
        }

        public static byte[] Deflate(byte[] data)
        {
            using (var ms = new MemoryStream())
            {
                using (var ds = new DeflateStream(ms, CompressionLevel.Optimal, true))
                {
                    ds.Write(data, 0, data.Length);
                }
                return ms.ToArray();
            }
        }
    }

    // Encrypts single 16-byte NG blocks by inverting the decryption rounds.
    // Every round maps each 32-bit output word from 4 distinct input bytes, so each word
    // is inverted independently with a meet-in-the-middle search over 2 x 65536 pairs.
    // Good for a handful of blocks (TOC entries), not for bulk data.
    public static class NgEncrypt
    {
        static readonly int[][] WordsA = { new[] { 0, 1, 2, 3 }, new[] { 4, 5, 6, 7 }, new[] { 8, 9, 10, 11 }, new[] { 12, 13, 14, 15 } };
        static readonly int[][] WordsB = { new[] { 0, 7, 10, 13 }, new[] { 1, 4, 11, 14 }, new[] { 2, 5, 8, 15 }, new[] { 3, 6, 9, 12 } };
        // hash of t[p0][a]^t[p1][b] -> (a | b<<8), chained, per (round, word)
        class HalfTable
        {
            public int[] Head = new int[1 << 17];
            public int[] Next = new int[65536];
            public uint[] Val = new uint[65536];
            public static int H(uint v) { return (int)((v * 2654435761u) >> 15); }
        }
        static readonly HalfTable[] Halves = new HalfTable[17 * 4];

        static int[] Pos(int round, int word) { return (round < 2 || round == 16) ? WordsA[word] : WordsB[word]; }

        static HalfTable Half(int round, int word)
        {
            int idx = round * 4 + word;
            lock (Halves)
            {
                if (Halves[idx] != null) return Halves[idx];
                var t = GtaKeys.NgTables[round];
                var p = Pos(round, word);
                var ht = new HalfTable();
                for (int i = 0; i < ht.Head.Length; i++) ht.Head[i] = -1;
                for (int ab = 0; ab < 65536; ab++)
                {
                    uint v = t[p[0]][ab & 0xFF] ^ t[p[1]][ab >> 8];
                    int h = HalfTable.H(v);
                    ht.Val[ab] = v;
                    ht.Next[ab] = ht.Head[h];
                    ht.Head[h] = ab;
                }
                Halves[idx] = ht;
                return ht;
            }
        }

        static void InvRound(byte[] buf, uint[] k, int round)
        {
            var t = GtaKeys.NgTables[round];
            var outp = new byte[16];
            for (int w = 0; w < 4; w++)
            {
                uint y = BitConverter.ToUInt32(buf, 4 * w) ^ k[4 * round + w];
                var p = Pos(round, w);
                var half = Half(round, w);
                bool found = false;
                for (int c = 0; c < 256 && !found; c++)
                {
                    uint yc = y ^ t[p[2]][c];
                    for (int d = 0; d < 256 && !found; d++)
                    {
                        uint need = yc ^ t[p[3]][d];
                        for (int ab = half.Head[HalfTable.H(need)]; ab >= 0; ab = half.Next[ab])
                        {
                            if (half.Val[ab] != need) continue;
                            outp[p[0]] = (byte)(ab & 0xFF);
                            outp[p[1]] = (byte)(ab >> 8);
                            outp[p[2]] = (byte)c;
                            outp[p[3]] = (byte)d;
                            found = true;
                            break;
                        }
                    }
                }
                if (!found) throw new Exception("NG: обратный раунд не найден");
            }
            Buffer.BlockCopy(outp, 0, buf, 0, 16);
        }

        public static byte[] EncryptBlock(byte[] plain, byte[] key)
        {
            var k = new uint[68];
            Buffer.BlockCopy(key, 0, k, 0, 272);
            var buf = new byte[16];
            Buffer.BlockCopy(plain, 0, buf, 0, 16);
            InvRound(buf, k, 16);
            for (int r = 15; r >= 2; r--) InvRound(buf, k, r);
            InvRound(buf, k, 1);
            InvRound(buf, k, 0);
            // self-check
            var back = Crypto.DecryptNg(buf, key);
            for (int i = 0; i < 16; i++) if (back[i] != plain[i]) throw new Exception("NG: проверка шифрования не пройдена");
            return buf;
        }
    }

    public enum RpfEnc : uint
    {
        NONE = 0,
        OPEN = 0x4E45504F,
        AES = 0x0FFFFFF9,
        NG = 0x0FEFFFFF,
    }

    public class RpfEntry
    {
        public RpfArchive Archive;
        public int Index;
        public string Name;
        public string Path;
        public uint NameOffset;
        public bool IsDir, IsResource;
        public uint EntriesIndex, EntriesCount;
        public uint FileOffset, FileSize, UncompressedSize;
        public bool IsEncrypted;
        public uint SysFlags, GfxFlags;

        public bool IsBinary { get { return !IsDir && !IsResource; } }

        public long StoredSize
        {
            get
            {
                if (IsResource) return FileSize;
                return FileSize == 0 ? UncompressedSize : FileSize;
            }
        }

        public void Write(BinaryWriter w)
        {
            if (IsDir)
            {
                w.Write(NameOffset); w.Write(0x7FFFFF00u); w.Write(EntriesIndex); w.Write(EntriesCount);
            }
            else if (IsResource)
            {
                uint fs = FileSize > 0xFFFFFF ? 0xFFFFFF : FileSize;
                w.Write((ushort)NameOffset);
                w.Write((byte)fs); w.Write((byte)(fs >> 8)); w.Write((byte)(fs >> 16));
                w.Write((byte)FileOffset); w.Write((byte)(FileOffset >> 8)); w.Write((byte)(((FileOffset >> 16) & 0x7F) | 0x80));
                w.Write(SysFlags); w.Write(GfxFlags);
            }
            else
            {
                w.Write((ushort)NameOffset);
                w.Write((byte)FileSize); w.Write((byte)(FileSize >> 8)); w.Write((byte)(FileSize >> 16));
                w.Write((byte)FileOffset); w.Write((byte)(FileOffset >> 8)); w.Write((byte)(FileOffset >> 16));
                w.Write(UncompressedSize);
                w.Write(IsEncrypted ? 1u : 0u);
            }
        }

        public override string ToString() { return Path; }
    }

    public class RpfArchive
    {
        public string Name;
        public string Path;
        public long StartPos;
        public long Size;
        public uint EntryCount, NamesLength, NamesFlags;   // some third-party packers set the top bits
        public RpfEnc Encryption;
        public byte[] NamesData;   // decrypted
        public byte[] RawEntries, RawNames;   // as stored (encrypted)
        public List<RpfEntry> Entries = new List<RpfEntry>();
        public RpfArchive Parent;
        public RpfEntry ParentEntry;

        public int HeaderLength { get { return 16 + (int)EntryCount * 16 + (int)NamesLength; } }

        public static RpfArchive Open(Stream s, long start, long size, string name, string path)
        {
            var a = new RpfArchive();
            a.Name = name; a.Path = path; a.StartPos = start; a.Size = size;
            s.Position = start;
            var br = new BinaryReader(s);
            uint ver = br.ReadUInt32();
            if (ver != 0x52504637) throw new Exception("Not an RPF7 archive: " + path);
            a.EntryCount = br.ReadUInt32();
            uint nl = br.ReadUInt32();
            a.NamesLength = nl & 0x0FFFFFFF;
            a.NamesFlags = nl & 0xF0000000;
            a.Encryption = (RpfEnc)br.ReadUInt32();
            byte[] ed = br.ReadBytes((int)a.EntryCount * 16);
            byte[] nd = br.ReadBytes((int)a.NamesLength);
            a.RawEntries = ed;
            a.RawNames = nd;
            if (a.Encryption == RpfEnc.AES)
            {
                ed = Crypto.DecryptAes(ed, GtaKeys.AesKey);
                nd = Crypto.DecryptAes(nd, GtaKeys.AesKey);
            }
            else if (a.Encryption != RpfEnc.OPEN && a.Encryption != RpfEnc.NONE)
            {
                ed = Crypto.DecryptNg(ed, name, (uint)size);
                nd = Crypto.DecryptNg(nd, name, (uint)size);
            }
            a.NamesData = nd;
            for (int i = 0; i < a.EntryCount; i++)
            {
                var e = new RpfEntry();
                e.Archive = a; e.Index = i;
                uint y = BitConverter.ToUInt32(ed, i * 16);
                uint x = BitConverter.ToUInt32(ed, i * 16 + 4);
                if (x == 0x7FFFFF00)
                {
                    e.IsDir = true;
                    e.NameOffset = y;
                    e.EntriesIndex = BitConverter.ToUInt32(ed, i * 16 + 8);
                    e.EntriesCount = BitConverter.ToUInt32(ed, i * 16 + 12);
                }
                else if ((x & 0x80000000) == 0)
                {
                    ulong buf = BitConverter.ToUInt64(ed, i * 16);
                    e.NameOffset = (uint)buf & 0xFFFF;
                    e.FileSize = (uint)(buf >> 16) & 0xFFFFFF;
                    e.FileOffset = (uint)(buf >> 40) & 0xFFFFFF;
                    e.UncompressedSize = BitConverter.ToUInt32(ed, i * 16 + 8);
                    e.IsEncrypted = BitConverter.ToUInt32(ed, i * 16 + 12) == 1;
                }
                else
                {
                    e.IsResource = true;
                    e.NameOffset = BitConverter.ToUInt16(ed, i * 16);
                    e.FileSize = (uint)ed[i * 16 + 2] | ((uint)ed[i * 16 + 3] << 8) | ((uint)ed[i * 16 + 4] << 16);
                    e.FileOffset = ((uint)ed[i * 16 + 5] | ((uint)ed[i * 16 + 6] << 8) | ((uint)ed[i * 16 + 7] << 16)) & 0x7FFFFF;
                    e.SysFlags = BitConverter.ToUInt32(ed, i * 16 + 8);
                    e.GfxFlags = BitConverter.ToUInt32(ed, i * 16 + 12);
                    if (e.FileSize == 0xFFFFFF)
                    {
                        long op = s.Position;
                        s.Position = start + (long)e.FileOffset * 512;
                        var hb = br.ReadBytes(16);
                        e.FileSize = ((uint)hb[7] << 0) | ((uint)hb[14] << 8) | ((uint)hb[5] << 16) | ((uint)hb[2] << 24);
                        s.Position = op;
                    }
                    e.IsEncrypted = false;
                }
                e.Name = ReadName(nd, (int)e.NameOffset);
                a.Entries.Add(e);
            }
            // paths
            a.Entries[0].Path = "";
            var stack = new Stack<RpfEntry>();
            stack.Push(a.Entries[0]);
            while (stack.Count > 0)
            {
                var d = stack.Pop();
                for (uint i = d.EntriesIndex; i < d.EntriesIndex + d.EntriesCount; i++)
                {
                    var e = a.Entries[(int)i];
                    e.Path = d.Path.Length == 0 ? e.Name : d.Path + "/" + e.Name;
                    if (e.IsDir) stack.Push(e);
                }
            }
            return a;
        }

        static string ReadName(byte[] nd, int off)
        {
            int end = off;
            while (end < nd.Length && nd[end] != 0) end++;
            return Encoding.ASCII.GetString(nd, off, end - off);
        }

        public RpfEntry Find(string path)
        {
            path = path.Replace('\\', '/').ToLowerInvariant();
            foreach (var e in Entries) if (e.Path != null && e.Path.ToLowerInvariant() == path) return e;
            return null;
        }

        public long DataPos(RpfEntry e) { return StartPos + (long)e.FileOffset * 512; }

        public RpfArchive OpenChild(Stream s, RpfEntry e)
        {
            var c = Open(s, DataPos(e), e.StoredSize, e.Name, Path + "/" + e.Path);
            c.Parent = this; c.ParentEntry = e;
            return c;
        }

        public byte[] ReadStored(Stream s, RpfEntry e)
        {
            s.Position = DataPos(e);
            var buf = new byte[e.StoredSize];
            int got = 0;
            while (got < buf.Length) { int n = s.Read(buf, got, buf.Length - got); if (n <= 0) break; got += n; }
            return buf;
        }

        public byte[] ExtractBinary(Stream s, RpfEntry e)
        {
            byte[] d = ReadStored(s, e);
            if (e.IsEncrypted)
            {
                if (Encryption == RpfEnc.AES) d = Crypto.DecryptAes(d, GtaKeys.AesKey);
                else d = Crypto.DecryptNg(d, e.Name, e.UncompressedSize);
            }
            if (e.FileSize > 0) d = Crypto.Inflate(d, 0);
            return d;
        }

        // Full .ytd/.ydr file as OpenIV exports it: 16 byte RSC7 header + deflated data.
        public byte[] ExtractResourceFile(Stream s, RpfEntry e)
        {
            byte[] d = ReadStored(s, e);
            // header stored in archive may hold packed size for huge files; rebuild a clean one
            var outp = (byte[])d.Clone();
            Buffer.BlockCopy(BitConverter.GetBytes(0x37435352u), 0, outp, 0, 4);
            Buffer.BlockCopy(BitConverter.GetBytes((uint)Rsc.GetVersion(e.SysFlags, e.GfxFlags)), 0, outp, 4, 4);
            Buffer.BlockCopy(BitConverter.GetBytes(e.SysFlags), 0, outp, 8, 4);
            Buffer.BlockCopy(BitConverter.GetBytes(e.GfxFlags), 0, outp, 12, 4);
            return outp;
        }

        public byte[] GetEntriesData()
        {
            using (var ms = new MemoryStream())
            {
                var w = new BinaryWriter(ms);
                foreach (var e in Entries) e.Write(w);
                return ms.ToArray();
            }
        }

        public byte[] BuildHeader(RpfEnc enc)
        {
            using (var ms = new MemoryStream())
            {
                var w = new BinaryWriter(ms);
                w.Write(0x52504637u); w.Write(EntryCount); w.Write(NamesLength | NamesFlags); w.Write((uint)enc);
                w.Write(GetEntriesData());
                w.Write(NamesData);
                return ms.ToArray();
            }
        }

        static long Align(long v, long a) { return (v + a - 1) / a * a; }

        public byte[] EntryPlain(RpfEntry e)
        {
            using (var ms = new MemoryStream())
            {
                e.Write(new BinaryWriter(ms));
                return ms.ToArray();
            }
        }

        // Encrypts one TOC entry the same way as the archive (NG key must be for `archiveSize`).
        public byte[] EncryptEntry(RpfEntry e, uint archiveSize)
        {
            return EncryptTocBlock(EntryPlain(e), archiveSize);
        }

        // One 16-byte block of the TOC (entries or names), encrypted like this archive.
        public byte[] EncryptTocBlock(byte[] plain, uint archiveSize)
        {
            if (Encryption == RpfEnc.NG) return NgEncrypt.EncryptBlock(plain, Crypto.GetNgKey(Name, archiveSize));
            if (Encryption == RpfEnc.AES) return Crypto.EncryptAesBlock(plain, GtaKeys.AesKey);
            return (byte[])plain.Clone();
        }

        public long NamesPos { get { return StartPos + 16 + (long)EntryCount * 16; } }

        // Smallest size >= minSize (multiple of 512) whose NG key equals the one for `Size`,
        // so every untouched encrypted TOC block stays valid.
        public long SizeKeepingKey(long minSize)
        {
            long n = Align(minSize, 512);
            if (Encryption != RpfEnc.NG) return n;
            uint want = Crypto.NgKeyIndex(Name, (uint)Size);
            for (int i = 0; i < 2000; i++, n += 512)
                if (Crypto.NgKeyIndex(Name, (uint)n) == want) return n;
            throw new Exception("Не удалось подобрать размер архива");
        }

        // Copies this (nested) archive and appends the replacement files at its end.
        // Untouched entries keep their offsets and encrypted TOC blocks; only the replaced
        // entries' blocks are re-encrypted, with the same key thanks to SizeKeepingKey.
        public byte[] AppendReplace(Stream s, Dictionary<string, byte[]> replace)
        {
            s.Position = StartPos;
            var orig = new byte[Size];
            int got = 0;
            while (got < orig.Length) { int n = s.Read(orig, got, orig.Length - got); if (n <= 0) throw new EndOfStreamException(); got += n; }

            long pos = Align(Size, 512);
            var changed = new List<RpfEntry>();
            var datas = new List<byte[]>();
            foreach (var e in Entries)
            {
                if (e.IsDir) continue;
                byte[] nd;
                if (!replace.TryGetValue(e.Path.ToLowerInvariant(), out nd)) continue;
                if (!e.IsResource) throw new Exception("Only resource replacement supported: " + e.Path);
                if (BitConverter.ToUInt32(nd, 0) != 0x37435352) throw new Exception("Not RSC7: " + e.Path);
                if (nd.Length > 0xFFFFFF) throw new Exception("Resource too large: " + e.Path);
                e.SysFlags = BitConverter.ToUInt32(nd, 8);
                e.GfxFlags = BitConverter.ToUInt32(nd, 12);
                e.FileSize = (uint)nd.Length;
                e.FileOffset = (uint)(pos / 512);
                changed.Add(e); datas.Add(nd);
                pos = Align(pos + nd.Length, 512);
            }
            if (changed.Count != replace.Count) throw new Exception("Не все файлы найдены в архиве");
            long newSize = SizeKeepingKey(pos);
            var outp = new byte[newSize];
            Buffer.BlockCopy(orig, 0, outp, 0, orig.Length);
            var blocks = new byte[changed.Count][];
            Parallel.For(0, changed.Count, delegate (int i) { blocks[i] = EncryptEntry(changed[i], (uint)newSize); });
            for (int i = 0; i < changed.Count; i++)
            {
                var e = changed[i];
                Buffer.BlockCopy(datas[i], 0, outp, (int)e.FileOffset * 512, datas[i].Length);
                Buffer.BlockCopy(blocks[i], 0, outp, 16 + e.Index * 16, 16);
            }
            return outp;
        }

        // Rebuilds this archive as a standalone OPEN archive, replacing the given files.
        // Unchanged entries are copied byte-for-byte (encrypted binaries stay encrypted:
        // their NG key depends only on name + size, which don't change).
        public byte[] Rebuild(Stream s, Dictionary<string, byte[]> replace)
        {
            var datas = new Dictionary<int, byte[]>();
            foreach (var e in Entries)
            {
                if (e.IsDir) continue;
                byte[] nd;
                if (replace.TryGetValue(e.Path.ToLowerInvariant(), out nd))
                {
                    if (!e.IsResource) throw new Exception("Only resource replacement supported: " + e.Path);
                    if (BitConverter.ToUInt32(nd, 0) != 0x37435352) throw new Exception("Not RSC7: " + e.Path);
                    e.SysFlags = BitConverter.ToUInt32(nd, 8);
                    e.GfxFlags = BitConverter.ToUInt32(nd, 12);
                    e.FileSize = (uint)nd.Length;
                    datas[e.Index] = nd;
                }
                else
                {
                    datas[e.Index] = ReadStored(s, e);
                }
            }
            long pos = Align(HeaderLength, 512);
            var order = new List<RpfEntry>();
            foreach (var e in Entries) if (!e.IsDir) order.Add(e);
            order.Sort(delegate (RpfEntry a, RpfEntry b) { return a.FileOffset.CompareTo(b.FileOffset); });
            foreach (var e in order)
            {
                e.FileOffset = (uint)(pos / 512);
                pos = Align(pos + datas[e.Index].Length, 512);
            }
            var outp = new byte[pos];
            var hdr = BuildHeader(RpfEnc.OPEN);
            Buffer.BlockCopy(hdr, 0, outp, 0, hdr.Length);
            foreach (var e in order)
            {
                var d = datas[e.Index];
                if (e.IsResource && d.Length > 0xFFFFFF)
                {
                    d = (byte[])d.Clone();
                    uint fs = (uint)d.Length;
                    d[7] = (byte)fs; d[14] = (byte)(fs >> 8); d[5] = (byte)(fs >> 16); d[2] = (byte)(fs >> 24);
                }
                Buffer.BlockCopy(d, 0, outp, (int)e.FileOffset * 512, d.Length);
            }
            return outp;
        }
    }

    public static class Rsc
    {
        public static int GetVersion(uint sys, uint gfx)
        {
            return (int)((((sys >> 28) & 0xF) << 4) + ((gfx >> 28) & 0xF));
        }

        public static int GetSize(uint flags)
        {
            uint s0 = ((flags >> 27) & 0x1) << 0;
            uint s1 = ((flags >> 26) & 0x1) << 1;
            uint s2 = ((flags >> 25) & 0x1) << 2;
            uint s3 = ((flags >> 24) & 0x1) << 3;
            uint s4 = ((flags >> 17) & 0x7F) << 4;
            uint s5 = ((flags >> 11) & 0x3F) << 5;
            uint s6 = ((flags >> 7) & 0xF) << 6;
            uint s7 = ((flags >> 5) & 0x3) << 7;
            uint s8 = ((flags >> 4) & 0x1) << 8;
            uint ss = flags & 0xF;
            uint baseSize = 0x200u << (int)ss;
            return (int)(baseSize * (s0 + s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8));
        }
    }
}
