# test_ci.ps1 — Run GitHub Actions build.yml steps locally (Windows)
# Usage: .\test_ci.ps1 [--skip-audit]
param([switch]$SkipAudit)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSCommandPath
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " LOCAL CI TEST — simple-kvm" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# --- Step 1: Install dependencies ---
Write-Host "`n[1/8] Install dependencies" -ForegroundColor Yellow
python -m pip install --upgrade pip
pip install -r app/requirements.txt
pip install "pyinstaller>=6.0,<7.0.0" "pyinstaller-hooks-contrib>=2024.0,<2027.0"

# --- Step 2: Security audit (optional) ---
if (-not $SkipAudit) {
    Write-Host "`n[2/8] Security audit" -ForegroundColor Yellow
    pip install pip-audit
    pip-audit -r app/requirements.txt
} else {
    Write-Host "`n[2/8] Security audit SKIPPED" -ForegroundColor DarkGray
}

# --- Step 3: Build with PyInstaller ---
Write-Host "`n[3/8] Build with PyInstaller" -ForegroundColor Yellow
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
python -m PyInstaller --clean simple-kvm.spec

# --- Step 4: Copy PySide6 plugins ---
Write-Host "`n[4/8] Copy PySide6 plugins" -ForegroundColor Yellow
$destPlugins = "dist/simple-kvm/_internal/PySide6/plugins"
if (Test-Path "$destPlugins/platforms/qwindows.dll") {
    Write-Host "  Plugins already bundled by PyInstaller hooks" -ForegroundColor Green
} else {
    Write-Host "  Plugins NOT bundled -- locating via pip show..." -ForegroundColor Yellow
    $location = $null
    python -m pip show PySide6 2>&1 | ForEach-Object {
        if ($_ -match '^Location:\s*(.+)$') { $location = $matches[1].Trim() }
    }
    if (-not $location) { throw "pip show PySide6 failed" }
    Write-Host "  PySide6 at: $location"
    $found = $false
    foreach ($dir in @("$location\PySide6\plugins", "$location\PySide6_Essentials\plugins")) {
        if (Test-Path "$dir\platforms\qwindows.dll") {
            Write-Host "  Found: $dir" -ForegroundColor Green
            New-Item -ItemType Directory -Force -Path $destPlugins | Out-Null
            Copy-Item -Recurse "$dir\*" $destPlugins -Force
            $found = $true
            break
        }
    }
    if (-not $found) { throw "Cannot find PySide6 plugins" }
}

# --- Step 5: Copy av.libs ---
Write-Host "`n[5/8] Copy av.libs FFmpeg DLLs" -ForegroundColor Yellow
$destAvlibs = "dist/simple-kvm/_internal/av.libs"
if (Test-Path "$destAvlibs/avcodec-*.dll") {
    Write-Host "  av.libs already bundled" -ForegroundColor Green
} else {
    Write-Host "  av.libs NOT bundled -- locating..." -ForegroundColor Yellow
    $location = $null
    python -m pip show av 2>&1 | ForEach-Object {
        if ($_ -match '^Location:\s*(.+)$') { $location = $matches[1].Trim() }
    }
    $src = "$location\av.libs"
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force -Path $destAvlibs | Out-Null
        Copy-Item -Recurse "$src\*" $destAvlibs -Force
        Write-Host "  Copied from: $src" -ForegroundColor Green
    } else {
        throw "av.libs not found at $src"
    }
}

# --- Step 6: Verify build output ---
Write-Host "`n[6/8] Verify build output" -ForegroundColor Yellow
if (-not (Test-Path "dist/simple-kvm/simple-kvm.exe")) { throw "EXE not found!" }
$pluginDlls = @(Get-ChildItem "dist/simple-kvm/_internal/PySide6/plugins/platforms/qwindows.dll" -ErrorAction SilentlyContinue)
if ($pluginDlls.Count -eq 0) { throw "Qt platform plugin (qwindows.dll) missing!" }
Write-Host "  qwindows.dll: $($pluginDlls[0].FullName)" -ForegroundColor Green
$ffmpegDlls = @(Get-ChildItem "dist/simple-kvm/_internal/av.libs/avcodec-*.dll" -ErrorAction SilentlyContinue)
if ($ffmpegDlls.Count -eq 0) { throw "FFmpeg DLLs missing!" }
Write-Host "  FFmpeg DLLs: $($ffmpegDlls.Count) files" -ForegroundColor Green
$size = [math]::Round(((Get-ChildItem -Recurse -File dist/simple-kvm/ | Measure-Object -Property Length -Sum).Sum)/1MB, 1)
Write-Host "  Total size: $size MB" -ForegroundColor Green

# --- Step 7: Inno Setup ---
Write-Host "`n[7/8] Build installer" -ForegroundColor Yellow
$innoDir = "${env:ProgramFiles(x86)}\Inno Setup 6"
if (-not (Test-Path "$innoDir\ISCC.exe")) { throw "Inno Setup not found" }
& "$innoDir\ISCC.exe" installer.iss 2>&1 | Select-Object -Last 5

# --- Step 8: SHA256 ---
Write-Host "`n[8/8] Generate checksum" -ForegroundColor Yellow
$installer = Get-ChildItem Output/simple-kvm-*-setup.exe | Select-Object -First 1
$hash = (Get-FileHash $installer.FullName -Algorithm SHA256).Hash
Write-Host "  SHA256: $hash" -ForegroundColor Green

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " ALL STEPS PASSED" -ForegroundColor Green
Write-Host " Installer: $($installer.FullName)" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
