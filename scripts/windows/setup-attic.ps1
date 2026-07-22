<#
  setup-attic.ps1  —  Windows-host preparation for the soulmount brain (SPEC §4.1, §Phase 4)

  WHAT THIS DOES (idempotent; safe to re-run):
    1. Task Scheduler boot job that starts the WSL distro at Windows startup
       (the linchpin of unattended recovery — WSL does NOT start on boot by itself).
    2. Networking so the robot can reach the brain on the LAN:
         - MIRRORED (preferred, Win11 22H2/23H2+, WSL 2.0+): sets .wslconfig +
           Hyper-V firewall inbound-allow for the brain/ssh ports.
         - PORTPROXY (fallback for older builds): netsh portproxy + firewall +
           a refresh task (the WSL IP changes each boot).
    3. Power plan: never sleep, hibernation off, Fast Startup off.
    4. Windows Update active hours set to the family's waking hours.

  THE CODING AGENT NEVER RUNS THIS. A household adult reviews it and runs it as
  Administrator (guardrail 2). BIOS "restore power after loss" must be set by hand.

  USAGE (elevated PowerShell):
    ./setup-attic.ps1 -Distro Ubuntu -Mode mirrored -BrainPort 8100 -SshPort 2222 `
                      -ActiveStart 7 -ActiveEnd 23
#>

param(
  [string]$Distro       = "Ubuntu",
  [ValidateSet("mirrored","portproxy")] [string]$Mode = "mirrored",
  [int]$BrainPort       = 8100,
  [int]$SshPort         = 2222,
  [int]$ActiveStart     = 7,     # Windows Update active hours start (24h)
  [int]$ActiveEnd       = 23     # ...end
)

$ErrorActionPreference = "Stop"
function Say($m){ Write-Host "• $m" -ForegroundColor Cyan }
function Ok ($m){ Write-Host "✓ $m" -ForegroundColor Green }
function Warn($m){ Write-Host "! $m" -ForegroundColor Yellow }

# Must be elevated.
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run this in an elevated (Administrator) PowerShell."
}

# ── 1. Task Scheduler: boot the distro at startup ────────────────────────────
Say "Task Scheduler: boot '$Distro' at startup (run whether logged on or not, highest privileges)"
$taskName = "soulmount-wsl-boot"
$action   = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro --exec /bin/true"
$trigger  = New-ScheduledTaskTrigger -AtStartup
$principal= New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
  -Settings $settings -Force | Out-Null
Ok "boot task '$taskName' registered"

# ── 2. Networking ────────────────────────────────────────────────────────────
if ($Mode -eq "mirrored") {
  Say "Mirrored networking: writing %UserProfile%\.wslconfig"
  $wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
  $desired = "[wsl2]`nnetworkingMode=mirrored`n"
  if ((-not (Test-Path $wslconfig)) -or ((Get-Content -Raw $wslconfig) -notmatch "networkingMode=mirrored")) {
    Set-Content -Path $wslconfig -Value $desired -Encoding utf8
    Ok "wrote $wslconfig (run 'wsl --shutdown' to apply)"
  } else { Ok ".wslconfig already mirrored" }

  Say "Hyper-V firewall: inbound-allow $BrainPort, $SshPort"
  # Mirrored mode shares ports with Windows; open them in the Hyper-V firewall.
  foreach ($p in @($BrainPort, $SshPort)) {
    $rule = "soulmount-in-$p"
    if (-not (Get-NetFirewallHyperVRule -Name $rule -ErrorAction SilentlyContinue)) {
      New-NetFirewallHyperVRule -Name $rule -DisplayName $rule -Direction Inbound `
        -Action Allow -Protocol TCP -LocalPorts $p -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' | Out-Null
      Ok "opened $p"
    } else { Ok "rule for $p already present" }
  }
  Warn "Mirrored mode shares ports with Windows — keep any Windows OpenSSH on 22 (WSL sshd is $SshPort)."
}
else {
  Say "Portproxy fallback: forward Windows ports -> current WSL IP"
  $wslIp = (wsl.exe -d $Distro --exec hostname -I).Trim().Split(" ")[0]
  foreach ($p in @($BrainPort, $SshPort)) {
    netsh interface portproxy delete v4tov4 listenport=$p listenaddress=0.0.0.0 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenport=$p listenaddress=0.0.0.0 connectport=$p connectaddress=$wslIp | Out-Null
    New-NetFirewallRule -DisplayName "soulmount-in-$p" -Direction Inbound -Action Allow `
      -Protocol TCP -LocalPort $p -ErrorAction SilentlyContinue | Out-Null
  }
  Ok "portproxy set to $wslIp (ports $BrainPort,$SshPort)"

  # The WSL IP changes each boot → a startup task refreshes the proxy target.
  Say "Registering portproxy-refresh task (WSL IP changes per boot)"
  $refresh = "wsl.exe -d $Distro --exec hostname -I | ForEach-Object { `$ip=`$_.Trim().Split(' ')[0]; " +
             "netsh interface portproxy set v4tov4 listenport=$BrainPort connectaddress=`$ip connectport=$BrainPort; " +
             "netsh interface portproxy set v4tov4 listenport=$SshPort connectaddress=`$ip connectport=$SshPort }"
  $ra = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -Command `"$refresh`""
  Register-ScheduledTask -TaskName "soulmount-portproxy-refresh" -Action $ra `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest) -Force | Out-Null
  Ok "portproxy-refresh task registered"
}

# ── 3. Power plan: never sleep, hibernation off, Fast Startup off ─────────────
Say "Power: never sleep, hibernation off, Fast Startup off"
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /change monitor-timeout-ac 0
powercfg /hibernate off
# Fast Startup interferes with scheduled tasks + networking on boot (§4.1).
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" `
  -Name HiberbootEnabled -Value 0 -ErrorAction SilentlyContinue
Ok "power plan set"

# ── 4. Windows Update active hours ────────────────────────────────────────────
Say "Windows Update active hours: $ActiveStart:00–$ActiveEnd:00"
$auKey = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
New-Item -Path $auKey -Force | Out-Null
Set-ItemProperty -Path $auKey -Name "ActiveHoursStart" -Value $ActiveStart -Type DWord
Set-ItemProperty -Path $auKey -Name "ActiveHoursEnd"   -Value $ActiveEnd   -Type DWord
Ok "active hours set"

Write-Host ""
Ok "setup-attic.ps1 complete."
Warn "MANUAL: set BIOS 'restore power after loss' = On. Then run 'wsl --shutdown' once to apply networking."
Warn "Verify from the laptop with: make verify-boot"
