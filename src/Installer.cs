// GUI installer for the custom GTA V map (RAGE:MP / NOVA RP).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace NovaMap
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
#if SELFTEST
            if (args.Length > 0) { SelfTest.Run(args); return; }
#endif
            Application.Run(new MainForm());
        }
    }

    static class Res
    {
        public static byte[] Get(string name)
        {
            using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
            {
                if (s == null) throw new Exception("Нет ресурса " + name);
                var ms = new MemoryStream();
                s.CopyTo(ms);
                return ms.ToArray();
            }
        }

        // texture set of a theme ("dark", "winter", ...) -> minimap_*.ytd
        public static Dictionary<string, byte[]> Theme(string variant) { return Prefixed(variant + ".", ".ytd"); }

        static Dictionary<string, byte[]> Prefixed(string prefix, string ext)
        {
            var d = new Dictionary<string, byte[]>();
            foreach (var n in Assembly.GetExecutingAssembly().GetManifestResourceNames())
                if (n.StartsWith(prefix) && n.EndsWith(ext)) d[n.Substring(prefix.Length)] = Get(n);
            if (d.Count == 0) throw new Exception("Нет данных для " + prefix);
            return d;
        }
    }

    // Builds the files to install for a theme + options.
    public class MapOptions
    {
        public string Theme = "dark";
        public bool Grid, Labels = true;

        public string Variant { get { return Theme; } }

        public string Tag
        {
            get { return Theme + (Grid ? "+grid" : "") + (Labels ? "+labels" : ""); }
        }

        public static string Describe(string tag)
        {
            var parts = new List<string>(tag.Split('+'));
            var names = new Dictionary<string, string> { { "dark", "тёмная" }, { "light", "светлая" }, { "winter", "зима" }, { "halloween", "хэллоуин" } };
            string t = parts[0].Replace("_relief", "");
            var outp = new List<string> { "тема «" + (names.ContainsKey(t) ? names[t] : t) + "»" };
            if (parts.Contains("relief") || parts[0].EndsWith("_relief")) outp.Add("рельеф");
            if (parts.Contains("grid")) outp.Add("сетка");
            if (parts.Contains("labels")) outp.Add("подписи");
            return string.Join(", ", outp);
        }
    }

    static class MapAssembler
    {
        static VectorPlan plan;

        public static VectorPlan Plan
        {
            get { if (plan == null) plan = VectorPlan.Load(Res.Get("vector_plan.bin")); return plan; }
        }

        public static Dictionary<string, byte[]> Textures(MapOptions o, Action<string> log)
        {
            var files = Res.Theme(o.Variant);
            if (!o.Labels && !o.Grid) return files;
            var th = Plan.Themes[Plan.ThemeIndex(o.Theme)];
            var big = new List<OverlayLayer>();
            var small = new List<OverlayLayer>();
            log("Накладываю " + (o.Grid && o.Labels ? "сетку и подписи" : o.Grid ? "сетку" : "подписи") + "...");
            if (o.Grid) AddLayers(big, small, "overlay_grid", new[] { 1, 0 }, new[] { th.OverlayColours[4], th.OverlayColours[3] });
            if (o.Labels) AddLayers(big, small, "overlay_labels", new[] { 1, 0, 2 }, new[] { th.OverlayColours[1], th.OverlayColours[0], th.OverlayColours[2] });
            for (int r = 0; r < 3; r++)
                for (int c = 0; c < 2; c++)
                {
                    string sea = "minimap_sea_" + r + "_" + c + ".ytd", lo = "minimap_" + r + "_" + c + ".ytd";
                    files[sea] = TextureOverlay.Apply(files[sea], big, c * 2048, r * 2048);
                    files[lo] = TextureOverlay.Apply(files[lo], small, c * 512, r * 512);
                }
            return files;
        }

        static void AddLayers(List<OverlayLayer> big, List<OverlayLayer> small, string res, int[] channels, byte[][] colours)
        {
            var b = Overlay.FromPng(Res.Get(res + ".png"));
            var s = Overlay.FromPng(Res.Get(res + "_small.png"));
            for (int i = 0; i < channels.Length; i++)
            {
                big.Add(new OverlayLayer { Mask = Channel(b, channels[i]), W = b.W, Colour = colours[i] });
                small.Add(new OverlayLayer { Mask = Channel(s, channels[i]), W = s.W, Colour = colours[i] });
            }
        }

        static byte[] Channel(Overlay o, int c) { return c == 0 ? o.C0 : c == 1 ? o.C1 : o.C2; }

        public static Dictionary<string, byte[]> Vector(MapOptions o, Dictionary<string, byte[]> vanilla)
        {
            var outp = new Dictionary<string, byte[]>();
            int ti = Plan.ThemeIndex(o.Theme);
            foreach (var kv in vanilla)
                outp[kv.Key] = Rsc7.Write(Plan.Apply(Rsc7.Read(kv.Value), kv.Key, ti, o.Grid, o.Labels));
            return outp;
        }
    }

    static class GameFinder
    {
        public static bool IsGameDir(string dir)
        {
            return !string.IsNullOrEmpty(dir) && File.Exists(Path.Combine(dir, "GTA5.exe"))
                && File.Exists(Path.Combine(dir, "update", "update.rpf"));
        }

        static string Reg(RegistryKey root, string key, string value)
        {
            try
            {
                using (var k = root.OpenSubKey(key))
                {
                    if (k == null) return null;
                    var v = k.GetValue(value) as string;
                    return string.IsNullOrEmpty(v) ? null : v.TrimEnd('\\', '/');
                }
            }
            catch { return null; }
        }

        public static string Find()
        {
            var cands = new List<string>();
            cands.Add(Reg(Registry.CurrentUser, @"Software\RAGE-MP", "game_v_path"));
            foreach (var v in new[] { "InstallFolderSteam", "InstallFolder", "InstallFolderEpic" })
                cands.Add(Reg(Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Rockstar Games\Grand Theft Auto V", v));
            cands.Add(Reg(Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Rockstar Games\GTAV", "InstallFolderSteam"));
            var steam = Reg(Registry.CurrentUser, @"Software\Valve\Steam", "SteamPath")
                ?? Reg(Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath");
            if (steam != null)
            {
                var libs = new List<string> { steam.Replace('/', '\\') };
                try
                {
                    var vdf = File.ReadAllText(Path.Combine(steam, "steamapps", "libraryfolders.vdf"));
                    foreach (Match m in Regex.Matches(vdf, "\"path\"\\s+\"([^\"]+)\""))
                        libs.Add(m.Groups[1].Value.Replace("\\\\", "\\"));
                }
                catch { }
                foreach (var l in libs) cands.Add(Path.Combine(l, "steamapps", "common", "Grand Theft Auto V"));
            }
            cands.Add(@"C:\Program Files\Rockstar Games\Grand Theft Auto V");
            cands.Add(@"C:\Program Files\Epic Games\GTAV");
            foreach (var c in cands) if (IsGameDir(c)) return c;
            return null;
        }
    }

    class ThemeCard : Panel
    {
        public bool Selected;
        public readonly string Theme;
        readonly PictureBox pic;
        readonly Label cap;
        public event EventHandler Picked;

        public void SetImage(Image img) { pic.Image = img; }

        public ThemeCard(string theme, string title, Image img)
        {
            Theme = theme;
            Size = new Size(176, 294);
            BackColor = Color.FromArgb(38, 39, 43);
            Padding = new Padding(6);
            Cursor = Cursors.Hand;
            pic = new PictureBox { Image = img, SizeMode = PictureBoxSizeMode.Zoom, Location = new Point(6, 6), Size = new Size(164, 246), Cursor = Cursors.Hand };
            cap = new Label { Text = title, ForeColor = Color.White, Font = new Font("Segoe UI Semibold", 10.5f), AutoSize = false, TextAlign = ContentAlignment.MiddleCenter, Location = new Point(6, 254), Size = new Size(164, 34), Cursor = Cursors.Hand };
            Controls.Add(pic);
            Controls.Add(cap);
            EventHandler h = delegate { if (Picked != null) Picked(this, EventArgs.Empty); };
            Click += h; pic.Click += h; cap.Click += h;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            var c = Selected ? Color.FromArgb(240, 84, 66) : Color.FromArgb(60, 61, 66);
            using (var p = new Pen(c, Selected ? 4 : 1))
                e.Graphics.DrawRectangle(p, 1, 1, Width - 3, Height - 3);
        }
    }

    class MainForm : Form
    {
        static readonly Color Bg = Color.FromArgb(28, 29, 32);
        static readonly Color Muted = Color.FromArgb(160, 163, 170);
        static readonly Color Accent = Color.FromArgb(226, 70, 56);

        TextBox pathBox;
        Label statusLbl, logLbl;
        Button installBtn, restoreBtn, browseBtn;
        ProgressBar bar;
        List<ThemeCard> cards = new List<ThemeCard>();
        CheckBox gridBox, labelsBox;
        Dictionary<string, Image> previews = new Dictionary<string, Image>();
        string gameDir;
        static readonly string[] ThemeIds = { "dark", "light", "winter", "halloween" };
        static readonly string[] ThemeNames = { "Тёмная", "Светлая", "Зима", "Хэллоуин" };

        public MainForm()
        {
            Text = "Кастомная карта GTA V — установщик";
            AutoScaleMode = AutoScaleMode.Dpi;
            AutoScaleDimensions = new SizeF(96f, 96f);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Bg;
            ForeColor = Color.White;
            Font = new Font("Segoe UI", 9.5f);
            ClientSize = new Size(774, 660);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            var title = new Label { Text = "Кастомная карта GTA V", Font = new Font("Segoe UI Semibold", 20f), AutoSize = true, Location = new Point(28, 20) };
            var sub = new Label { Text = "Большая карта и мини-карта: темы, подписи районов и дорог, сетка квадратов.", ForeColor = Muted, AutoSize = false, Size = new Size(720, 22), Location = new Point(30, 64) };
            Controls.Add(title); Controls.Add(sub);

            var pl = new Label { Text = "Папка GTA V", ForeColor = Muted, AutoSize = true, Location = new Point(28, 100) };
            pathBox = new TextBox { ReadOnly = true, Location = new Point(30, 122), Size = new Size(614, 26), BackColor = Color.FromArgb(44, 45, 50), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
            browseBtn = MakeButton("Обзор…", false);
            browseBtn.Location = new Point(654, 120); browseBtn.Size = new Size(90, 29);
            browseBtn.Click += delegate { Browse(); };
            Controls.Add(pl); Controls.Add(pathBox); Controls.Add(browseBtn);

            statusLbl = new Label { AutoSize = false, Size = new Size(714, 22), Location = new Point(30, 156), ForeColor = Muted };
            Controls.Add(statusLbl);

            for (int i = 0; i < ThemeIds.Length; i++)
            {
                var card = new ThemeCard(ThemeIds[i], ThemeNames[i], null);
                card.Location = new Point(30 + i * 184, 186);
                var c = card;
                card.Picked += delegate { Pick(c); };
                cards.Add(card);
                Controls.Add(card);
            }
            Pick(cards[0]);

            labelsBox = new CheckBox { Text = "Подписи районов и дорог", ForeColor = Color.White, AutoSize = true, Location = new Point(30, 492), Cursor = Cursors.Hand, Checked = true };
            gridBox = new CheckBox { Text = "Сетка квадратов", ForeColor = Color.White, AutoSize = true, Location = new Point(270, 492), Cursor = Cursors.Hand };
            foreach (var cb in new[] { labelsBox, gridBox })
            {
                cb.CheckedChanged += delegate { UpdatePreviews(); };
                Controls.Add(cb);
            }
            UpdatePreviews();

            installBtn = MakeButton("Установить", true);
            installBtn.Location = new Point(30, 526); installBtn.Size = new Size(350, 42);
            installBtn.Click += delegate { Run(true); };
            restoreBtn = MakeButton("Вернуть оригинальную карту", false);
            restoreBtn.Location = new Point(394, 526); restoreBtn.Size = new Size(350, 42);
            restoreBtn.Click += delegate { Run(false); };
            Controls.Add(installBtn); Controls.Add(restoreBtn);

            bar = new ProgressBar { Location = new Point(30, 578), Size = new Size(714, 6), Style = ProgressBarStyle.Marquee, Visible = false };
            logLbl = new Label { AutoSize = false, Size = new Size(714, 22), Location = new Point(30, 588), ForeColor = Color.White };
            var note = new Label { Text = "Перед установкой закройте игру и RAGE:MP. После обновления GTA V или проверки файлов в Steam установку нужно повторить.", ForeColor = Muted, Font = new Font("Segoe UI", 8.25f), AutoSize = false, Size = new Size(714, 34), Location = new Point(30, 614) };
            Controls.Add(bar); Controls.Add(logLbl); Controls.Add(note);

            Shown += delegate
            {
                SetGame(GameFinder.Find());
                if (gameDir == null) logLbl.Text = "Игра не найдена автоматически — укажите папку через «Обзор…».";
            };
        }

        Button MakeButton(string text, bool primary)
        {
            var b = new Button { Text = text, FlatStyle = FlatStyle.Flat, ForeColor = Color.White, Cursor = Cursors.Hand };
            b.BackColor = primary ? Accent : Color.FromArgb(48, 49, 54);
            b.FlatAppearance.BorderColor = primary ? Accent : Color.FromArgb(70, 71, 77);
            b.FlatAppearance.MouseOverBackColor = primary ? Color.FromArgb(240, 92, 76) : Color.FromArgb(60, 61, 67);
            if (primary) b.Font = new Font("Segoe UI Semibold", 10.5f);
            return b;
        }

        void Pick(ThemeCard c)
        {
            foreach (var k in cards) { k.Selected = k == c; k.Invalidate(); }
        }

        Image Preview(string theme)
        {
            string key = theme + "_" + (labelsBox.Checked ? "1" : "0") + (gridBox.Checked ? "1" : "0");
            Image img;
            if (!previews.TryGetValue(key, out img))
            {
                img = Image.FromStream(new MemoryStream(Res.Get("preview_" + key + ".jpg")));
                previews[key] = img;
            }
            return img;
        }

        void UpdatePreviews()
        {
            if (cards.Count == 0 || gridBox == null || labelsBox == null) return;
            foreach (var c in cards) c.SetImage(Preview(c.Theme));
        }

        void Browse()
        {
            using (var d = new FolderBrowserDialog { Description = "Укажите папку Grand Theft Auto V (где лежит GTA5.exe)" })
            {
                if (gameDir != null) d.SelectedPath = gameDir;
                if (d.ShowDialog(this) != DialogResult.OK) return;
                if (!GameFinder.IsGameDir(d.SelectedPath))
                {
                    if (File.Exists(Path.Combine(d.SelectedPath, "GTA5_Enhanced.exe")))
                        MessageBox.Show(this, "Это GTA V Enhanced — она не поддерживается (RAGE:MP работает на обычной версии).", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    else
                        MessageBox.Show(this, "В этой папке нет GTA5.exe и update\\update.rpf.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                SetGame(d.SelectedPath);
            }
        }

        void SetGame(string dir)
        {
            gameDir = dir;
            pathBox.Text = dir ?? "";
            installBtn.Enabled = restoreBtn.Enabled = dir != null;
            RefreshStatus();
        }

        void RefreshStatus()
        {
            if (gameDir == null) { statusLbl.Text = ""; return; }
            try
            {
                var t = new Patcher().InstalledTheme(gameDir);
                statusLbl.Text = t == null ? "Сейчас: оригинальная карта" : "Сейчас: установлена кастомная карта (" + MapOptions.Describe(t) + ")";
                statusLbl.ForeColor = t == null ? Muted : Color.FromArgb(120, 210, 140);
            }
            catch (Exception ex) { statusLbl.Text = "Не удалось прочитать update.rpf: " + ex.Message; }
        }

        static string[] GameProcesses = { "GTA5", "PlayGTAV", "GTAVLauncher", "ragemp_v", "ragemp_game_ui" };

        void Run(bool install)
        {
            var running = GameProcesses.Where(p => Process.GetProcessesByName(p).Length > 0).ToList();
            if (running.Count > 0)
            {
                MessageBox.Show(this, "Сначала закройте игру / RAGE:MP (запущено: " + string.Join(", ", running) + ").", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            var opt = new MapOptions { Grid = gridBox.Checked, Labels = labelsBox.Checked };
            foreach (var c in cards) if (c.Selected) opt.Theme = c.Theme;
            installBtn.Enabled = restoreBtn.Enabled = browseBtn.Enabled = false;
            bar.Visible = true;
            string dir = gameDir;
            var th = new Thread(delegate ()
            {
                string result = null;
                bool ok = true;
                try
                {
                    var p = new Patcher();
                    p.Log = delegate (string m) { UI(delegate { logLbl.Text = m; }); };
                    UI(delegate { logLbl.Text = "Ищу ключи игры в GTA5.exe..."; });
                    GtaKeys.LoadFromGame(dir, Res.Get("magic.dat"));
                    if (install)
                    {
                        var tex = MapAssembler.Textures(opt, p.Log);
                        p.Install(dir, opt.Tag, tex, delegate (Dictionary<string, byte[]> van) { return MapAssembler.Vector(opt, van); });
                        result = "Карта установлена! Можно запускать игру.";
                    }
                    else
                    {
                        bool done = p.RestoreAll(dir);
                        result = done ? "Оригинальная карта возвращена." : "Кастомная карта не установлена — возвращать нечего.";
                    }
                }
                catch (UnauthorizedAccessException)
                {
                    ok = false;
                    result = "Нет доступа к файлам игры. Запустите установщик от имени администратора.";
                }
                catch (IOException ex)
                {
                    ok = false;
                    result = "Файл игры занят или недоступен (закройте игру, лаунчеры и OpenIV).\n\n" + ex.Message;
                }
                catch (Exception ex)
                {
                    ok = false;
                    result = "Ошибка: " + ex.Message;
                }
                UI(delegate
                {
                    bar.Visible = false;
                    installBtn.Enabled = restoreBtn.Enabled = browseBtn.Enabled = true;
                    logLbl.Text = ok ? result : "Не получилось — подробности в сообщении.";
                    RefreshStatus();
                    MessageBox.Show(this, result, Text, MessageBoxButtons.OK, ok ? MessageBoxIcon.Information : MessageBoxIcon.Error);
                });
            });
            th.IsBackground = true;
            th.Start();
        }

        void UI(MethodInvoker a)
        {
            if (IsDisposed) return;
            BeginInvoke(a);
        }
    }
}
