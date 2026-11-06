# Installs and restores on copies of the game's archives (the game itself is only read):
# C# tiles vs the Python reference, install over the current state, installed tiles and textures
# vs their references, restore back to the player's own original (H0). Needs build\rpftool.exe,
# build\vector_expected and tools\keys\aes.bin. Run from anywhere; leaves nothing behind.
param([string]$Game = "D:\SteamLibrary\steamapps\common\Grand Theft Auto V")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
$root = (Get-Location).Path
$keys = @("tools\keys\aes.bin", "src\magic.dat")
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$themes = @("dark", "light", "winter", "halloween", "sakura")

& $csc -nologo -optimize "-out:build\rpftool.exe" -r:System.Drawing.dll src\NovaRpf.cs src\Patcher.cs src\MapBuild.cs src\RpfTool.cs
if ($LASTEXITCODE -ne 0) { throw "csc rpftool failed" }
foreach ($d in Get-ChildItem build\vector_expected -Directory) {
    $p = $d.Name.Split("_")
    "vectest $($d.Name): " + (& .\build\rpftool.exe vectest @keys build\vector_plan.bin $p[0] $p[1] $p[2] $d.FullName files\game\minimap_ydd)
}

(Get-Content src\app.manifest -Raw).Replace('requireAdministrator', 'asInvoker') | Set-Content build\test.manifest -Encoding UTF8
$res = @("-resource:src\magic.dat,magic.dat", "-resource:build\vector_plan.bin,vector_plan.bin")
foreach ($o in @("overlay_labels", "overlay_labels_small", "overlay_grid", "overlay_grid_small")) { $res += "-resource:build\$o.png,$o.png" }
Get-ChildItem "build\installer\preview_*.jpg" | ForEach-Object { $res += "-resource:$($_.FullName),$($_.Name)" }
foreach ($t in $themes) { Get-ChildItem "dist\ytd\$t\*.ytd" | ForEach-Object { $res += "-resource:$($_.FullName),$t.$($_.Name)" } }
& $csc -nologo -optimize -define:SELFTEST -target:winexe "-out:build\installer_test.exe" "-win32icon:src\app.ico" "-win32manifest:build\test.manifest" -r:System.Windows.Forms.dll -r:System.Drawing.dll @res src\NovaRpf.cs src\Patcher.cs src\MapBuild.cs src\Installer.cs src\SelfTest.cs
if ($LASTEXITCODE -ne 0) { throw "csc test failed" }

function Selftest([string[]]$a) {
    $log = "$root\build\st.log"
    Start-Process build\installer_test.exe -ArgumentList ($a + $log) -Wait
    Get-Content $log -Encoding UTF8 | Select-Object -Last 1
}

$t = "$root\build\testgame"
try {
    New-Item -ItemType Directory -Force "$t\update" | Out-Null
    Copy-Item "$Game\update\update.rpf" "$t\update\"
    Copy-Item "$Game\x64e.rpf", "$Game\GTA5.exe" $t
    foreach ($b in @("update\update.rpf.novamap.bak", "x64e.rpf.novamap.bak")) { if (Test-Path "$Game\$b") { Copy-Item "$Game\$b" "$t\$b" } }
    "game copy: update.rpf " + (Get-Item "$t\update\update.rpf").Length + ", our map installed: " + (Test-Path "$t\x64e.rpf.novamap.bak")

    # install over the current state, then take the player's own original as the reference
    "install over current state: " + (Selftest @("--install", $t, "dark", "1", "1"))
    Selftest @("--restore", $t) | Out-Null
    $h0u = (Get-FileHash "$t\update\update.rpf").Hash
    $h0x = (Get-FileHash "$t\x64e.rpf").Hash
    "original: update.rpf $h0u, x64e.rpf $h0x"

    New-Item -ItemType Directory -Force build\chk | Out-Null
    $inner = "x64/data/cdimages/scaleform_generic.rpf"
    foreach ($d in Get-ChildItem build\vector_expected -Directory) {
        $p = $d.Name.Split("_")
        "install $($d.Name): " + (Selftest @("--install", $t, $p[0], $p[1], $p[2]))
        "  " + (& .\build\rpftool.exe vecinstalled @keys "$t\x64e.rpf" $d.FullName)
        $labels, $grid = "-", "-"
        $labelsS, $gridS = "-", "-"
        if ($p[2] -eq "1") { $labels = "build\overlay_labels.png"; $labelsS = "build\overlay_labels_small.png" }
        if ($p[1] -eq "1") { $grid = "build\overlay_grid.png"; $gridS = "build\overlay_grid_small.png" }
        foreach ($c in @(@("sea_1_0", 0, 2048, $labels, $grid), @("1_1", 512, 512, $labelsS, $gridS))) {
            & .\build\rpftool.exe extract @keys "$t\update\update.rpf" "$inner/minimap_$($c[0]).ytd" "build\chk\inst.ytd" | Out-Null
            $src = "dist\ytd\$($p[0])\minimap_$($c[0]).ytd"
            if ($c[3] -eq "-" -and $c[4] -eq "-") { $ref = $src }
            else {
                & .\build\rpftool.exe texapply @keys build\vector_plan.bin $p[0] $src build\chk\ref.ytd $c[1] $c[2] $c[3] $c[4] | Out-Null
                $ref = "build\chk\ref.ytd"
            }
            "  texture $($c[0]) identical: " + ((Get-FileHash build\chk\inst.ytd).Hash -eq (Get-FileHash $ref).Hash)
        }
    }
    Selftest @("--restore", $t) | Out-Null
    "restored update.rpf == original: " + ((Get-FileHash "$t\update\update.rpf").Hash -eq $h0u)
    "restored x64e.rpf == original: " + ((Get-FileHash "$t\x64e.rpf").Hash -eq $h0x)
    Selftest @("--screenshot", $t, "$root\build\preview\installer_ui.png") | Out-Null
}
finally {
    Remove-Item -Recurse -Force $t, build\chk -ErrorAction SilentlyContinue
    Remove-Item build\st.log, build\test.manifest, build\installer_test.exe -ErrorAction SilentlyContinue
}
