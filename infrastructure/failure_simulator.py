from utils.powershell_runner import run_ps
from utils.logger import get_logger
import time

log = get_logger("failure_simulator")

STORAGE_VM = "AcmePDC02"

# Virtual disk names (must match storage_manager.py)
VDISK_VOL1  = "Vol1"   # RAID/Parity — E:
VDISK_VOL2  = "Vol2"   # RAID/Parity — F:
SIMPLE_DISK = "G:"     # Simple volume — no resilience


# ------------------------------------------------
# Helper: Run inside storage VM
# ------------------------------------------------

def run_on_vm(ps_script):
    wrapped = f"""
Invoke-Command -VMName "{STORAGE_VM}" -ScriptBlock {{
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


# ------------------------------------------------
# Create test files before simulation
# ------------------------------------------------

def create_test_files():
    """
    Seeds test data on all volumes so we can verify
    what survives vs what is lost after a failure.
    """

    log.info("[SIM] Creating test files on all volumes...")

    ps = """
# E: (RAID Vol1)
$ePath = "E:\\Vol1Test"
if (-not (Test-Path $ePath)) { New-Item -Path $ePath -ItemType Directory -Force }
Set-Content -Path "$ePath\\test_raid.txt"   -Value "RAID data - should survive disk failure"
Set-Content -Path "$ePath\\important.txt"   -Value "Important file on parity volume"

# F: (RAID Vol2)
$fPath = "F:\\Vol2Test"
if (-not (Test-Path $fPath)) { New-Item -Path $fPath -ItemType Directory -Force }
Set-Content -Path "$fPath\\test_raid2.txt"  -Value "Vol2 RAID data"

# G: (Simple Vol3 - no resilience)
$gPath = "G:\\Vol3Test"
if (-not (Test-Path $gPath)) { New-Item -Path $gPath -ItemType Directory -Force }
Set-Content -Path "$gPath\\test_simple.txt" -Value "SIMPLE disk data - will be lost on failure"

Write-Output "Test files created on E:, F:, G:"
"""
    run_on_vm(ps)


# ------------------------------------------------
# Simulate simple disk failure (G: — no resilience)
# ------------------------------------------------

def simulate_simple_disk_failure():
    """
    Simulates failure of the simple (non-RAID) G: volume.
    Demonstrates data loss on non-resilient storage.
    """

    log.info("[SIM] ⚠ Simulating SIMPLE DISK FAILURE on G: ...")

    ps = """
# Find the physical disk backing G:
$vol = Get-Volume -DriveLetter G -ErrorAction SilentlyContinue

if (-not $vol) {
    Write-Output "G: volume not found."
    exit
}

$partition = Get-Partition -DriveLetter G
$disk = Get-Disk -Number $partition.DiskNumber

# Take disk offline to simulate failure
Set-Disk -Number $disk.Number -IsOffline $true

Write-Output "Disk offline: $($disk.Number) — G: is now inaccessible (data loss simulation)"
"""
    run_on_vm(ps)
    log.warning("[SIM] G: taken offline. This simulates complete data loss on a simple volume.")


# ------------------------------------------------
# Simulate RAID disk failure (Vol1 — parity volume)
# ------------------------------------------------

def simulate_raid_disk_failure():
    """
    Retires one physical disk from the storage pool to simulate
    a RAID member failure. The parity virtual disk degrades but
    remains accessible (demonstrating RAID resilience).
    """

    log.info("[SIM] ⚠ Simulating RAID DISK FAILURE on Pool1 ...")

    ps = f"""
Import-Module Storage

$pool = Get-StoragePool -FriendlyName "Pool1" -ErrorAction SilentlyContinue

if (-not $pool) {{
    Write-Output "Storage pool not found."
    exit
}}

# Pick one pool member to retire (simulate hardware failure)
$diskToFail = Get-PhysicalDisk -StoragePool $pool |
    Where-Object {{ $_.OperationalStatus -eq "OK" }} |
    Select-Object -First 1

if (-not $diskToFail) {{
    Write-Output "No healthy disks found in pool."
    exit
}}

# Retire the disk (sets it to Retired state — simulates failure)
Set-PhysicalDisk -UniqueId $diskToFail.UniqueId -Usage Retired

Write-Output "Retired disk: $($diskToFail.FriendlyName) — Pool degraded"
Write-Output "Check virtual disk health with: Get-VirtualDisk"
"""
    run_on_vm(ps)
    log.warning(f"[SIM] One pool disk retired. '{VDISK_VOL1}' and '{VDISK_VOL2}' are degraded but still accessible.")


# ------------------------------------------------
# Check virtual disk health
# ------------------------------------------------

def check_virtual_disk_health():
    log.info("[SIM] Checking virtual disk health...")

    ps = """
Get-VirtualDisk | Select-Object FriendlyName, OperationalStatus, HealthStatus |
    Format-Table -AutoSize

Get-PhysicalDisk | Select-Object FriendlyName, OperationalStatus, HealthStatus |
    Format-Table -AutoSize
"""
    result = run_on_vm(ps)
    if result:
        log.info(result)
    return result


# ------------------------------------------------
# Rebuild RAID (replace failed disk and repair)
# ------------------------------------------------

def rebuild_raid():
    """
    Removes the retired disk from the pool and triggers a rebuild
    using a spare disk, simulating the RAID recovery process.
    """

    log.info("[SIM] 🔧 Initiating RAID rebuild...")

    ps = """
Import-Module Storage

$pool = Get-StoragePool -FriendlyName "Pool1" -ErrorAction SilentlyContinue

if (-not $pool) {
    Write-Output "Storage pool not found."
    exit
}

# Find the retired disk
$retiredDisk = Get-PhysicalDisk -StoragePool $pool |
    Where-Object { $_.Usage -eq "Retired" }

if (-not $retiredDisk) {
    Write-Output "No retired disks found. Nothing to rebuild."
    exit
}

Write-Output "Retired disk found: $($retiredDisk.FriendlyName)"

# Find a new poolable disk to add as replacement
$subsystem = Get-StorageSubSystem -FriendlyName "Windows Storage*"
$spareDisk = Get-PhysicalDisk -StorageSubSystem $subsystem |
    Where-Object { $_.CanPool -eq $true } |
    Select-Object -First 1

if (-not $spareDisk) {
    Write-Output "No spare disk available for rebuild."
    exit
}

# Add spare to pool
Add-PhysicalDisk -StoragePoolFriendlyName "Pool1" -PhysicalDisks $spareDisk
Write-Output "Spare disk added: $($spareDisk.FriendlyName)"

# Remove the retired disk
Remove-PhysicalDisk -StoragePoolFriendlyName "Pool1" -PhysicalDisks $retiredDisk
Write-Output "Retired disk removed from pool."

# Repair virtual disks
Get-VirtualDisk | Where-Object { $_.HealthStatus -ne "Healthy" } | Repair-VirtualDisk
Write-Output "RAID rebuild initiated. Monitor with: Get-VirtualDisk"
"""
    run_on_vm(ps)
    log.info("[SIM] RAID rebuild started. Data is being reconstructed on the spare disk.")


# ------------------------------------------------
# Recover simple disk (bring back online)
# ------------------------------------------------

def recover_simple_disk():
    """
    Brings the simple disk back online.
    In a real failure, data would be lost — this just ends the simulation.
    """

    log.info("[SIM] 🔧 Recovering simple disk (bringing G: back online)...")

    ps = """
# Find offline disk
$offlineDisk = Get-Disk | Where-Object { $_.OperationalStatus -eq "Offline" } |
    Select-Object -First 1

if ($offlineDisk) {
    Set-Disk -Number $offlineDisk.Number -IsOffline $false
    Write-Output "Disk brought online: $($offlineDisk.Number)"
    Write-Output "NOTE: In a real failure scenario, data on this disk would be lost."
} else {
    Write-Output "No offline disks found."
}
"""
    run_on_vm(ps)


# ------------------------------------------------
# Full failure simulation demo
# ------------------------------------------------

def run_failure_demo():
    """
    Runs a guided failure simulation demonstrating:
    1. Simple disk failure → data loss
    2. RAID disk failure → degraded but accessible
    3. RAID rebuild
    4. Recovery
    """

    log.info("\n" + "=" * 55)
    log.info("  ACME LAB — STORAGE FAILURE SIMULATION")
    log.info("=" * 55 + "\n")

    # --- Setup ---
    log.info("STEP 1: Creating test data on all volumes...")
    create_test_files()
    time.sleep(2)

    # --- Simple disk failure ---
    log.info("\nSTEP 2: Simulating SIMPLE disk failure (G:)...")
    simulate_simple_disk_failure()
    time.sleep(3)

    log.info("\nSTEP 3: Checking health after simple disk failure...")
    check_virtual_disk_health()
    time.sleep(2)

    # --- RAID disk failure ---
    log.info("\nSTEP 4: Simulating RAID disk failure (Pool1)...")
    simulate_raid_disk_failure()
    time.sleep(3)

    log.info("\nSTEP 5: Confirming RAID volume still accessible despite failure...")
    check_virtual_disk_health()
    time.sleep(2)

    # --- Rebuild ---
    log.info("\nSTEP 6: Rebuilding RAID with spare disk...")
    rebuild_raid()
    time.sleep(5)

    log.info("\nSTEP 7: Checking health post-rebuild...")
    check_virtual_disk_health()
    time.sleep(2)

    # --- Simple disk recovery ---
    log.info("\nSTEP 8: Recovering simple disk (simulation end)...")
    recover_simple_disk()

    log.info("\n" + "=" * 55)
    log.info("  SIMULATION COMPLETE")
    log.info("  Key lessons:")
    log.info("  - Simple volumes: NO protection, data lost on failure")
    log.info("  - Parity (RAID): degraded but accessible, rebuilds")
    log.info("=" * 55 + "\n")