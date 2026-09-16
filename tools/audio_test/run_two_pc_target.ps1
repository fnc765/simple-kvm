[CmdletBinding()]
param(
    [ValidateSet("install", "prepare")]
    [string]$Operation = "prepare",
    [string]$HostName = "100.114.238.82",
    [string]$UserName = "choco",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\id_ed25519_simple_kvm_fmvu34017",
    [string]$PythonExe = "C:\Users\choco\Documents\programming\simple-kvm\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$policy = Join-Path $repoRoot "tools\verification_policy.py"
$controller = Join-Path $repoRoot "tools\audio_test\controller.py"

# This hook intentionally runs before every remote operation. Deployment is
# not a validation run; PREPARE is a zero-second intermediate verification.
& $PythonExe $policy --name "two-PC target $Operation" --stage intermediate --duration 0
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $PythonExe $controller `
    --host $HostName `
    --user $UserName `
    --identity $IdentityFile `
    $Operation
exit $LASTEXITCODE
