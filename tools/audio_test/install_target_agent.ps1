[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseRoot,
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    [string]$TaskName = "SimpleKvmBenchTarget"
)

$ErrorActionPreference = "Stop"
$release = $ReleaseRoot
$agent = Join-Path $release "tools\audio_test\target_agent.py"
$requirements = Join-Path $release "tools\audio_test\target_requirements.txt"
$venv = Join-Path $Root "venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $agent)) {
    throw "Target agent not found: $agent"
}

New-Item -ItemType Directory -Path $Root -Force | Out-Null
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonExe -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed: $LASTEXITCODE" }
}
& $venvPython -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) { throw "dependency installation failed: $LASTEXITCODE" }

# OpenSSH sessions on a workgroup machine can expose USERDOMAIN=WORKGROUP,
# which Task Scheduler cannot map back to the local account SID.  The local
# SAM account is always addressed by COMPUTERNAME\USERNAME here.
$identity = "$env:COMPUTERNAME\$env:USERNAME"
$argument = '"{0}" --root "{1}"' -f $agent, $Root
$action = New-ScheduledTaskAction `
    -Execute $venvPython `
    -Argument $argument `
    -WorkingDirectory $release
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
[pscustomobject]@{
    Root = $Root
    Python = $venvPython
    TaskName = $task.TaskName
    TaskState = $task.State
    UserId = $task.Principal.UserId
    LogonType = $task.Principal.LogonType
    RunLevel = $task.Principal.RunLevel
    Execute = $task.Actions.Execute
    Arguments = $task.Actions.Arguments
} | ConvertTo-Json -Depth 4
