# ACME Lab Destroy Script
# Stops and removes all VMs and lab resources

Write-Host "Starting ACME Lab cleanup..." -ForegroundColor Yellow

# VM names
$vmNames = @(
"AcmeRtr01",
"AcmePDC01",
"AcmeWks1001"
)

# Lab folder
$labPath = "C:\CVNP-Python\Python Projects\Lab Deployment\LabVMs"

# Stop VMs
foreach ($vm in $vmNames) {
    if (Get-VM -Name $vm -ErrorAction SilentlyContinue) {
        Write-Host "Stopping $vm"
        Stop-VM -Name $vm -Force -TurnOff -ErrorAction SilentlyContinue
    }
}

# Remove VMs
foreach ($vm in $vmNames) {
    if (Get-VM -Name $vm -ErrorAction SilentlyContinue) {
        Write-Host "Removing $vm"
        Remove-VM -Name $vm -Force
    }
}

# Remove virtual switch
$switchName = "AcmeBusiness"

if (Get-VMSwitch -Name $switchName -ErrorAction SilentlyContinue) {
    Write-Host "Removing virtual switch $switchName"
    Remove-VMSwitch -Name $switchName -Force
}

# Delete VM files
if (Test-Path $labPath) {
    Write-Host "Deleting VM folder $labPath"
    Remove-Item $labPath -Recurse -Force
}

Write-Host "ACME Lab environment fully removed." -ForegroundColor Green