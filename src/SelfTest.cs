#if SELFTEST
// Test-only entry points (compiled with -define:SELFTEST, never in the shipped exe).
using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace NovaMap
{
    static class SelfTest
    {
        public static void Run(string[] args)
        {
            var log = new StreamWriter(args[args.Length - 1]) { AutoFlush = true };
            try
            {
                if (args[0] == "--screenshot")
                {
                    // --screenshot gameDir out.png log
                    var f = new MainForm();
                    f.StartPosition = FormStartPosition.Manual;
                    f.Location = new Point(-4000, -4000);
                    f.ShowInTaskbar = false;
                    f.Show();
                    Application.DoEvents();
                    var bmp = new Bitmap(f.Width, f.Height);
                    f.DrawToBitmap(bmp, new Rectangle(0, 0, f.Width, f.Height));
                    bmp.Save(args[2]);
                    log.WriteLine("screenshot ok " + f.Width + "x" + f.Height);
                    f.Close();
                }
                else if (args[0] == "--install")
                {
                    // --install gameDir theme grid labels log   (flags 0/1)
                    var p = new Patcher();
                    p.Log = log.WriteLine;
                    log.WriteLine("found game: " + GameFinder.Find());
                    GtaKeys.LoadFromGame(args[1], Res.Get("magic.dat"));
                    var opt = new MapOptions { Theme = args[2], Grid = args[3] == "1", Labels = args[4] == "1" };
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    var files = MapAssembler.Textures(opt, log.WriteLine);
                    log.WriteLine("theme files: " + files.Count + " (" + sw.ElapsedMilliseconds + " ms)");
                    p.Install(args[1], opt.Tag, files, delegate (System.Collections.Generic.Dictionary<string, byte[]> van) { return MapAssembler.Vector(opt, van); });
                    log.WriteLine("installed theme: " + p.InstalledTheme(args[1]) + " in " + sw.ElapsedMilliseconds + " ms");
                    log.WriteLine("installed theme: " + p.InstalledTheme(args[1]));
                }
                else if (args[0] == "--restore")
                {
                    var p = new Patcher();
                    p.Log = log.WriteLine;
                    GtaKeys.LoadFromGame(args[1], Res.Get("magic.dat"));
                    log.WriteLine("restore: " + p.RestoreAll(args[1]));
                }
            }
            catch (Exception ex) { log.WriteLine("ERROR " + ex); }
            log.Close();
        }
    }
}
#endif
