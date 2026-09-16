[CmdletBinding()]
param(
    [ValidateSet("intermediate", "final-integration")]
    [string]$Stage = "intermediate",
    [double]$Seconds = 10,
    [int]$Cycles = 5,
    [string]$HostName = "100.114.238.82",
    [string]$UserName = "choco",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519_simple_kvm_fmvu34017",
    [string]$PythonExe = "C:\Users\choco\Documents\programming\simple-kvm\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$policy = Join-Path $repoRoot "tools\verification_policy.py"
$runner = Join-Path $repoRoot "tools\audio_test\two_pc_hid.py"

& $PythonExe $policy `
    --name "two-PC BP1/BP2 HID" `
    --stage $Stage `
    --duration $Seconds
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $PythonExe $runner `
    --host $HostName `
    --user $UserName `
    --identity $IdentityFile `
    --stage $Stage `
    --seconds $Seconds `
    --cycles $Cycles
exit $LASTEXITCODE
