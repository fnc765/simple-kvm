[CmdletBinding()]
param(
    [string]$OutputDir = (Join-Path ([System.IO.Path]::GetTempPath()) "simple-kvm-audio-native")
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$policy = & python (Join-Path $repoRoot "tools\verification_policy.py") `
    --name "native audio unit test" --stage intermediate --duration 60
$policy | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    throw "VERIFICATION_POLICY_FAIL stage=native"
}
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw "AUDIO_FAIL stage=native prerequisite=vswhere"
}

$vsInstall = & $vswhere -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
if (-not $vsInstall) {
    throw "AUDIO_FAIL stage=native prerequisite=msvc"
}

$vcvars = Join-Path $vsInstall "VC\Auxiliary\Build\vcvars64.bat"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$exe = Join-Path $OutputDir "audio_core_tests.exe"
$include = Join-Path $repoRoot "firmware\common"
$sources = @(
    (Join-Path $repoRoot "tests\native\audio_core_tests.cpp"),
    (Join-Path $repoRoot "firmware\common\audio_frame.cpp"),
    (Join-Path $repoRoot "firmware\common\audio_ring.cpp"),
    (Join-Path $repoRoot "firmware\common\audio_asrc.cpp"),
    (Join-Path $repoRoot "firmware\common\audio_session.cpp")
    (Join-Path $repoRoot "firmware\common\audio_control.cpp")
    (Join-Path $repoRoot "firmware\common\audio_pipeline.cpp")
)
$quotedSources = ($sources | ForEach-Object { '"' + $_ + '"' }) -join " "
$compile = 'call "{0}" >nul && cl /nologo /std:c++17 /EHsc /O2 /W4 /WX /I"{1}" /Fe:"{2}" {3}' -f `
    $vcvars, $include, $exe, $quotedSources

Push-Location $OutputDir
try {
    & cmd.exe /d /s /c $compile
    if ($LASTEXITCODE -ne 0) {
        throw "AUDIO_FAIL stage=native_compile exit=$LASTEXITCODE"
    }
    & $exe
    if ($LASTEXITCODE -ne 0) {
        throw "AUDIO_FAIL stage=native_test exit=$LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
