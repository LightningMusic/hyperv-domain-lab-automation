# ACME Lab Destroy Script — stops and removes ALL lab VMs and resources

Write-Host "Starting ACME Lab cleanup..." -ForegroundColor Yellow

$vmNames = @(
    "AcmeRtr01",
    "AcmePDC01",
    "AcmePDC02",
    "AcmeWks1001",
    "AcmeWeb01"
)

$labPath = "C:\CVNP-Python\Python Projects\Lab Deployment\LabVMs"

# Stop VMs
foreach ($vm in $vmNames) {
    if (Get-VM -Name $vm -ErrorAction SilentlyContinue) {
        Write-Host "Stopping $vm" -ForegroundColor Cyan
        Stop-VM -Name $vm -Force -TurnOff -ErrorAction SilentlyContinue
    }
}

# Remove VMs (VHDs auto-deleted with -Force on newer PS)
foreach ($vm in $vmNames) {
    if (Get-VM -Name $vm -ErrorAction SilentlyContinue) {
        Write-Host "Removing $vm" -ForegroundColor Cyan
        Remove-VM -Name $vm -Force
    }
}

# Remove virtual switches
foreach ($sw in @("AcmeBusiness", "ACME-External")) {
    if (Get-VMSwitch -Name $sw -ErrorAction SilentlyContinue) {
        Write-Host "Removing switch: $sw" -ForegroundColor Cyan
        Remove-VMSwitch -Name $sw -Force
    }
}

# Delete all VM files
if (Test-Path $labPath) {
    Write-Host "Deleting LabVMs folder: $labPath" -ForegroundColor Cyan
    Remove-Item $labPath -Recurse -Force
}

# Clear deployment state
$stateFile = "C:\CVNP-Python\Python Projects\Lab Deployment\logs\deployment_state.json"
if (Test-Path $stateFile) {
    Remove-Item $stateFile -Force
    Write-Host "Cleared deployment state." -ForegroundColor Cyan
}

Write-Host "`nACME Lab fully removed." -ForegroundColor Green