# destroy_lab.ps1 — ACME Lab full teardown
# Always runs non-interactively (called from Python via -NonInteractive PS session)

param([switch]$Force)   # accepted but ignored — always force when called from Python

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

Write-Host "`nStarting ACME Lab cleanup..." -ForegroundColor Yellow

# Ensure vmms is running
$svc = Get-Service vmms -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne 'Running') {
    Write-Host "Starting vmms..." -ForegroundColor Cyan
    Start-Service vmms
    Start-Sleep 5
}

# Stop VMs
foreach ($vm in $vmNames) {
    $obj = Get-VM -Name $vm -ErrorAction SilentlyContinue
    if ($obj) {
        if ($obj.State -ne 'Off') {
            Write-Host "Stopping $vm..." -ForegroundColor Cyan
            Stop-VM -Name $vm -Force -TurnOff -ErrorAction SilentlyContinue
            $deadline = (Get-Date).AddSeconds(30)
            while ((Get-VM -Name $vm -ErrorAction SilentlyContinue).State -ne 'Off' -and (Get-Date) -lt $deadline) {
                Start-Sleep 2
            }
        }
    }
}

# Remove VMs and their VHDs
foreach ($vm in $vmNames) {
    $obj = Get-VM -Name $vm -ErrorAction SilentlyContinue
    if ($obj) {
        Write-Host "Removing $vm" -ForegroundColor Cyan
        $vhds = Get-VMHardDiskDrive -VMName $vm -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Path
        Remove-VM -Name $vm -Force -ErrorAction SilentlyContinue
        foreach ($vhd in $vhds) {
            if ($vhd -and (Test-Path $vhd)) {
                Remove-Item $vhd -Force -ErrorAction SilentlyContinue
                Write-Host "  Deleted VHD: $vhd" -ForegroundColor DarkGray
            }
        }
    }
}

# Remove virtual switches
foreach ($sw in $switchNames) {
    if (Get-VMSwitch -Name $sw -ErrorAction SilentlyContinue) {
        Write-Host "Removing switch: $sw" -ForegroundColor Cyan
        Remove-VMSwitch -Name $sw -Force -ErrorAction SilentlyContinue
    }
}

# Delete LabVMs folder
if (Test-Path $LabPath) {
    Write-Host "Deleting LabVMs folder: $LabPath" -ForegroundColor Cyan
    Remove-Item $LabPath -Recurse -Force -ErrorAction SilentlyContinue
}

# Clear deployment state file
if (Test-Path $StateFile) {
    Remove-Item $StateFile -Force -ErrorAction SilentlyContinue
    Write-Host "Cleared deployment state." -ForegroundColor Cyan
}

# Clean up temp_unattend ISOs
$unattendDir = Join-Path $ScriptDir "temp_unattend"
if (Test-Path $unattendDir) {
    Get-ChildItem $unattendDir -Filter "*.iso" |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host "`nACME Lab fully removed.`n" -ForegroundColor Green