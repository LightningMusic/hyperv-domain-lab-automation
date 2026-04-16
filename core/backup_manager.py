from utils.powershell_runner import run_ps
from utils.logger import get_logger

log = get_logger("storage_manager")

STORAGE_VM = "AcmePDC02"

# Drive letter assignments
VOL_E = "E"   # RAID/Parity - Vol1
VOL_F = "F"   # RAID/Parity - Vol2
VOL_G = "G"   # Simple disk - Vol3

POOL_NAME = "Pool1"
POOL_FRIENDLY = "ACME Storage Pool"


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
# Initialize raw disks (bring online + initialize)
# ------------------------------------------------

def initialize_disks():
    """
    Brings all raw/offline disks online and initializes them as GPT.
    Skips disks that already have a partition style.
    """

    log.info("[STORAGE] Initializing raw disks...")

    ps = """
$rawDisks = Get-Disk | Where-Object {
    $_.PartitionStyle -eq "RAW" -or $_.OperationalStatus -eq "Offline"
}

foreach ($disk in $rawDisks) {
    Set-Disk -Number $disk.Number -IsOffline $false
    Set-Disk -Number $disk.Number -IsReadOnly $false

    if ($disk.PartitionStyle -eq "RAW") {
        Initialize-Disk -Number $disk.Number -PartitionStyle GPT
        Write-Output "Initialized disk $($disk.Number)"
    }
}

Write-Output "Disk initialization complete. Total raw disks processed: $($rawDisks.Count)"
"""
    result = run_on_vm(ps)
    if result:
        log.info(result)


# ------------------------------------------------
# Create simple volume (G: drive — standalone disk)
# ------------------------------------------------

def create_simple_volume(drive_letter=VOL_G, label="Vol3", size_gb=None):
    """
    Creates a simple partition + NTFS volume on the next available disk.
    If size_gb is None, uses the full disk.
    """

    log.info(f"[STORAGE] Creating simple volume {drive_letter}: ({label})")

    size_param = f"-Size {size_gb}GB" if size_gb else "-UseMaximumSize"

    ps = f"""
# Find a basic disk with no partitions (not part of a storage pool)
$disk = Get-Disk | Where-Object {{
    $_.PartitionStyle -eq "GPT" -and
    (Get-Partition -DiskNumber $_.Number -ErrorAction SilentlyContinue) -eq $null
}} | Sort-Object Size | Select-Object -First 1

if (-not $disk) {{
    Write-Output "No suitable disk found for simple volume {drive_letter}:"
    exit
}}

$partition = New-Partition `
    -DiskNumber $disk.Number `
    {size_param} `
    -DriveLetter "{drive_letter}"

Format-Volume `
    -DriveLetter "{drive_letter}" `
    -FileSystem NTFS `
    -NewFileSystemLabel "{label}" `
    -Confirm:$false

Write-Output "Created simple volume {drive_letter}: on disk $($disk.Number)"
"""
    run_on_vm(ps)


# ------------------------------------------------
# Create storage pool from multiple disks
# ------------------------------------------------

def create_storage_pool(pool_name=POOL_NAME, disk_count=5):
    """
    Creates a storage pool from available physical disks.
    Uses primordial pool disks (unallocated).
    """

    log.info(f"[STORAGE] Creating storage pool '{pool_name}' from {disk_count} disks...")

    ps = f"""
$subsystem = Get-StorageSubSystem -FriendlyName "Windows Storage*"

$availableDisks = Get-PhysicalDisk -StorageSubSystem $subsystem |
    Where-Object {{ $_.CanPool -eq $true }} |
    Select-Object -First {disk_count}

if ($availableDisks.Count -lt 2) {{
    Write-Error "Not enough poolable disks. Found: $($availableDisks.Count)"
    exit 1
}}

$existing = Get-StoragePool -FriendlyName "{pool_name}" -ErrorAction SilentlyContinue

if (-not $existing) {{
    New-StoragePool `
        -FriendlyName "{pool_name}" `
        -StorageSubSystemFriendlyName "Windows Storage*" `
        -PhysicalDisks $availableDisks

    Write-Output "Storage pool '{pool_name}' created with $($availableDisks.Count) disks."
}} else {{
    Write-Output "Storage pool '{pool_name}' already exists."
}}
"""
    run_on_vm(ps)


# ------------------------------------------------
# Create RAID-like parity virtual disk
# ------------------------------------------------

def create_parity_virtual_disk(vdisk_name, size_gb, drive_letter, label):
    """
    Creates a parity (RAID-5 equivalent) virtual disk in Pool1,
    then creates a partition and NTFS volume on it.
    """

    log.info(f"[STORAGE] Creating parity virtual disk '{vdisk_name}' → {drive_letter}: ({label})")

    ps = f"""
$pool = Get-StoragePool -FriendlyName "{POOL_NAME}" -ErrorAction SilentlyContinue

if (-not $pool) {{
    Write-Error "Storage pool '{POOL_NAME}' not found."
    exit 1
}}

$existing = Get-VirtualDisk -FriendlyName "{vdisk_name}" -ErrorAction SilentlyContinue

if (-not $existing) {{
    $vdisk = New-VirtualDisk `
        -StoragePoolFriendlyName "{POOL_NAME}" `
        -FriendlyName "{vdisk_name}" `
        -Size {size_gb}GB `
        -ResiliencySettingName "Parity" `
        -ProvisioningType Fixed

    Write-Output "Virtual disk '{vdisk_name}' created."

    # Initialize the new virtual disk
    $disk = $vdisk | Get-Disk
    Initialize-Disk -Number $disk.Number -PartitionStyle GPT

    $partition = New-Partition `
        -DiskNumber $disk.Number `
        -UseMaximumSize `
        -DriveLetter "{drive_letter}"

    Format-Volume `
        -DriveLetter "{drive_letter}" `
        -FileSystem NTFS `
        -NewFileSystemLabel "{label}" `
        -Confirm:$false

    Write-Output "Volume {drive_letter}: ({label}) ready."
}} else {{
    Write-Output "Virtual disk '{vdisk_name}' already exists."
}}
"""
    run_on_vm(ps)


# ------------------------------------------------
# Create shared folders on storage volumes
# ------------------------------------------------

def create_storage_shares():
    """Creates the Vol1Test and Vol3Test SMB shares."""

    log.info("[STORAGE] Creating storage shares...")

    shares = [
        {"name": "Vol1Test", "path": "E:\\Vol1Test", "drive": "E"},
        {"name": "Vol3Test", "path": "G:\\Vol3Test", "drive": "G"},
    ]

    for share in shares:
        ps = f"""
$path = "{share['path']}"
$name = "{share['name']}"

if (-not (Test-Path $path)) {{
    New-Item -Path $path -ItemType Directory -Force
}}

if (-not (Get-SmbShare -Name $name -ErrorAction SilentlyContinue)) {{
    New-SmbShare `
        -Name $name `
        -Path $path `
        -FullAccess "Everyone"
    Write-Output "Created share: $name"
}} else {{
    Write-Output "Share already exists: $name"
}}
"""
        run_on_vm(ps)


# ------------------------------------------------
# Verify storage configuration
# ------------------------------------------------

def verify_storage():
    log.info("[STORAGE] Verifying storage configuration...")

    ps = """
Write-Output "=== Storage Pools ==="
Get-StoragePool | Where-Object { $_.IsPrimordial -eq $false } |
    Select-Object FriendlyName, OperationalStatus, HealthStatus | Format-Table

Write-Output "=== Virtual Disks ==="
Get-VirtualDisk | Select-Object FriendlyName, OperationalStatus, HealthStatus | Format-Table

Write-Output "=== Volumes ==="
Get-Volume | Where-Object { $_.DriveLetter -in @('E','F','G') } |
    Select-Object DriveLetter, FileSystemLabel, HealthStatus, SizeRemaining | Format-Table
"""
    result = run_on_vm(ps)
    if result:
        log.info(result)


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def configure_storage():
    log.info("\n[STORAGE] Starting storage configuration on AcmePDC02...\n")

    # Step 1: Bring all raw disks online
    initialize_disks()

    # Step 2: Create simple G: volume from a standalone 50GB disk
    create_simple_volume(drive_letter=VOL_G, label="Vol3", size_gb=45)

    # Step 3: Create storage pool from 5x 30GB disks
    create_storage_pool(pool_name=POOL_NAME, disk_count=5)

    # Step 4: Create parity virtual disks on the pool
    create_parity_virtual_disk("Vol1", size_gb=40, drive_letter=VOL_E, label="Vol1")
    create_parity_virtual_disk("Vol2", size_gb=40, drive_letter=VOL_F, label="Vol2")

    # Step 5: Create SMB shares on the volumes
    create_storage_shares()

    # Step 6: Verify everything looks good
    verify_storage()

    log.info("\n[STORAGE] Storage configuration COMPLETE.\n")