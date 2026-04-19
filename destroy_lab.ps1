# destroy_lab.ps1 — ACME Lab full teardown
# Works regardless of CWD because all paths are derived from this script's location.

param(
    [switch]$Force   # skip confirmation prompt when $true
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LabPath   = Join-Path $ScriptDir "LabVMs"
$StateFile = Join-Path $ScriptDir "logs\deployment_state.json"

$vmNames = @(
    "AcmeRtr01",
    "AcmePDC01",
    "AcmePDC02",
    "AcmeWks1001",
    "AcmeWeb01"
)

$switchNames = @("AcmeBusiness", "ACME-External")

# ── Confirmation ──────────────────────────────────────────────────────────────
if (-not $Force) {
    $reply = Read-Host "This will DELETE all ACME lab VMs and data. Continue? [y/N]"
    if ($reply -notmatch '^[Yy]') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

Write-Host "`nStarting ACME Lab cleanup..." -ForegroundColor Yellow

# ── Ensure vmms is running so Hyper-V cmdlets work ───────────────────────────
$svc = Get-Service vmms -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne 'Running') {
    Write-Host "Starting vmms..." -ForegroundColor Cyan
    Start-Service vmms
    Start-Sleep 5
}

# ── Stop VMs ──────────────────────────────────────────────────────────────────
foreach ($vm in $vmNames) {
    $obj = Get-VM -Name $vm -ErrorAction SilentlyContinue
    if ($obj) {
        if ($obj.State -ne 'Off') {
            Write-Host "Stopping $vm..." -ForegroundColor Cyan
            Stop-VM -Name $vm -Force -TurnOff -ErrorAction SilentlyContinue
            # Wait up to 30s for the VM to reach Off state
            $deadline = (Get-Date).AddSeconds(30)
            while ((Get-VM -Name $vm).State -ne 'Off' -and (Get-Date) -lt $deadline) {
                Start-Sleep 2
            }
        }
    }
}

# ── Remove VMs ────────────────────────────────────────────────────────────────
foreach ($vm in $vmNames) {
    $obj = Get-VM -Name $vm -ErrorAction SilentlyContinue
    if ($obj) {
        Write-Host "Removing $vm" -ForegroundColor Cyan
        # Collect VHD paths before removing the VM record
        $vhds = Get-VMHardDiskDrive -VMName $vm -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Path
        Remove-VM -Name $vm -Force -ErrorAction SilentlyContinue
        # Remove any VHDs that weren't automatically deleted
        foreach ($vhd in $vhds) {
            if ($vhd -and (Test-Path $vhd)) {
                Remove-Item $vhd -Force -ErrorAction SilentlyContinue
                Write-Host "  Deleted VHD: $vhd" -ForegroundColor DarkGray
            }
        }
    }
}

# ── Remove virtual switches ───────────────────────────────────────────────────
foreach ($sw in $switchNames) {
    $obj = Get-VMSwitch -Name $sw -ErrorAction SilentlyContinue
    if ($obj) {
        Write-Host "Removing switch: $sw" -ForegroundColor Cyan
        Remove-VMSwitch -Name $sw -Force -ErrorAction SilentlyContinue
    }
}

# ── Delete LabVMs folder ──────────────────────────────────────────────────────
if (Test-Path $LabPath) {
    Write-Host "Deleting LabVMs folder: $LabPath" -ForegroundColor Cyan
    Remove-Item $LabPath -Recurse -Force -ErrorAction SilentlyContinue
}

# ── Clear deployment state ────────────────────────────────────────────────────
if (Test-Path $StateFile) {
    Remove-Item $StateFile -Force -ErrorAction SilentlyContinue
    Write-Host "Cleared deployment state." -ForegroundColor Cyan
}

# ── Clean up temp_unattend ISO files (keep XMLs) ─────────────────────────────
$unattendDir = Join-Path $ScriptDir "temp_unattend"
if (Test-Path $unattendDir) {
    Get-ChildItem $unattendDir -Filter "*.iso" | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "Cleaned temp_unattend ISO files." -ForegroundColor DarkGray
}

Write-Host "`nACME Lab fully removed.`n" -ForegroundColor Green