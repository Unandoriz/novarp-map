# Builds dist\NovaMap_Installer.exe (single file: code + magic.dat + base textures of the 4 themes
# + label/grid overlays + vector plan + previews). Overlays and vector tiles are composed at install time.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
New-Item -ItemType Directory -Force dist | Out-Null
$res = @("-resource:src\magic.dat,magic.dat", "-resource:build\vector_plan.bin,vector_plan.bin")
foreach ($o in @("overlay_labels", "overlay_labels_small", "overlay_grid", "overlay_grid_small")) {
    $res += "-resource:build\$o.png,$o.png"
}
Get-ChildItem "build\installer\preview_*.jpg" | ForEach-Object { $res += "-resource:$($_.FullName),$($_.Name)" }
foreach ($t in @("dark", "light", "winter", "halloween")) {
    Get-ChildItem "dist\ytd\$t\*.ytd" | ForEach-Object { $res += "-resource:$($_.FullName),$t.$($_.Name)" }
}
& $csc -nologo -optimize -target:winexe "-out:dist\NovaMap_Installer.exe" `
    "-win32icon:src\app.ico" "-win32manifest:src\app.manifest" `
    -r:System.Windows.Forms.dll -r:System.Drawing.dll `
    @res src\NovaRpf.cs src\Patcher.cs src\MapBuild.cs src\Installer.cs
if ($LASTEXITCODE -ne 0) { throw "csc failed" }
Get-Item dist\NovaMap_Installer.exe | Select-Object Name, Length
