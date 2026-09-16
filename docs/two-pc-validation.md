# Two-PC hardware validation

The controller PC (`fnchoco`) owns BP1. The target laptop (`FMVU34017`)
owns BP2. They communicate over the existing, host-key-verified SSH link; the
target agent itself runs from a limited, interactive-logon Scheduled Task so
WASAPI and Raw Input use the unlocked physical desktop instead of the SSH
session.

## Safety and wiring

- Connect BP1 and BP2 through the project's SPI/UART/GND harness.
- Connect BP1 USB only to the controller PC and BP2 USB only to the laptop.
- Share signal ground, but never connect the two USB 5 V rails together.
- Keep the laptop logged on and unlocked during HID verification.

## Deployment and readiness

Run from the audio worktree in PowerShell:

```powershell
tools\audio_test\run_two_pc_target.ps1 -Operation install
tools\audio_test\run_two_pc_target.ps1 -Operation prepare
```

Deployment is content-addressed. Every request carries the SHA-256 candidate
identifier and the target rejects it if it does not match the deployed
release. `PREPARE` must report the interactive session, all four BP2 composite
interfaces, both BP2 Raw Input mouse interfaces, and one BP2 capture endpoint.

## Validation time policy

Every entry point prints and enforces the policy before touching hardware:

- intermediate checks are at most 60 seconds;
- the single final integration check is at least 300 seconds.

The normal smoke run is:

```powershell
tools\audio_test\run_two_pc_hid.ps1 -Stage intermediate -Seconds 10
tools\audio_test\run_two_pc_e2e.ps1 -Stage intermediate -Seconds 10
```

The HID runner opens no LAN listener. It tunnels a target-local safety socket
through the authenticated SSH connection. Before every HID report, the target
rechecks that the opaque full-screen shield is still visible and foreground,
then replies `SAFE`. Any other response stops injection. Keyboard and mouse
release reports are sent during cleanup and the original target cursor is
restored.

Only after the smoke result passes and all review findings are closed, run the
single final integration:

```powershell
tools\audio_test\run_two_pc_e2e.ps1 -Stage final-integration -Seconds 300
```

Evidence is written under `logs/two_pc/<timestamp>/`. It includes the exact
candidate identifier, both machine identities, BP1 diagnostic pages, target
capture metadata, the raw PCM capture, waveform metrics, and a final PASS/FAIL
marker. These evidence files are intentionally ignored by Git.
