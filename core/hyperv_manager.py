"""
core/hyperv_manager.py
All paths, VM names, and credentials come from config_loader.
Key improvements:
  - vmms service health check before every Hyper-V operation
  - Fixed unattend ISO creation (IMAPI2FS replaced with New-IsoFile pure-PS approach)
  - Parallel install detection for all VMs
  - Retry wrapper on VM creation
  - Absolute path for destroy script
"""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from config_loader import (
    load_config, get_lab_root, get_unattend_dir,
    get_server_iso, get_win11_iso,
    get_router_name, get_dc_name, get_workstation_name,
    get_internal_switch, get_external_switch, get_admin_password
)
from utils.powershell_runner import run_ps
from utils.logger import get_logger

log = get_logger("hyperv_manager")

LAB_ROOT       = get_lab_root()
UNATTEND_DIR   = get_unattend_dir()
SERVER_ISO     = get_server_iso()
WIN11_ISO      = get_win11_iso()
SWITCH_NAME    = get_internal_switch()
ADMIN_PASS     = get_admin_password()
ROUTER_VM      = get_router_name()
DC_VM          = get_dc_name()
WORKSTATION_VM = get_workstation_name()
CHECKPOINT_FILE = os.path.join(LAB_ROOT, "deployment_state.txt")

# ── Checkpoint helpers ───────────────────────────────────────────────────────

def _save_cp(step):
    os.makedirs(LAB_ROOT, exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(step)


def _load_cp():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return f.read().strip()
    return None


def run_step(step, func):
    if _load_cp() == step:
        log.info(f"[SKIP] {step}")
        return
    log.info(f"[RUN]  {step}")
    func()
    _save_cp(step)


# ── vmms health guard ────────────────────────────────────────────────────────

def ensure_vmms_running():
    """
    Ensure the Hyper-V Virtual Machine Management service is running.
    If it crashed or is stopped, restart it before issuing any Hyper-V cmdlets.
    Called at the top of every Hyper-V operation block.
    """
    run_ps("""
$svc = Get-Service -Name vmms -ErrorAction SilentlyContinue
if (-not $svc) { Write-Output "vmms service not found - Hyper-V may not be installed"; exit }
if ($svc.Status -ne 'Running') {
    Write-Output "vmms not running ($($svc.Status)) — restarting..."
    Start-Service vmms
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Service vmms).Status -ne 'Running' -and (Get-Date) -lt $deadline) {
        Start-Sleep 2
    }
}
$status = (Get-Service vmms).Status
Write-Output "vmms: $status"
if ($status -ne 'Running') { throw "vmms failed to start" }
""")


# ── Validation ──────────────────────────────────────────────────────────────

def verify_environment():
    log.info("[VERIFY] Checking Hyper-V, vmms, and ISOs")
    ensure_vmms_running()
    run_ps("""
$f = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
if ($f.State -ne "Enabled") { throw "Hyper-V is not enabled on this machine." }
Write-Output "Hyper-V OK"
""")
    for iso in (SERVER_ISO, WIN11_ISO):
        if not os.path.exists(iso):
            raise FileNotFoundError(f"ISO not found: {iso}")
    log.info("[VERIFY] Environment OK")


verify_hyperv_installed = verify_environment   # alias


def verify_iso_files():
    for iso in (SERVER_ISO, WIN11_ISO):
        if not os.path.exists(iso):
            raise FileNotFoundError(f"ISO not found: {iso}")
    log.info("ISOs verified.")


def create_lab_directory():
    os.makedirs(LAB_ROOT, exist_ok=True)
    log.info(f"Lab directory ready: {LAB_ROOT}")


def create_unattend_directory():
    os.makedirs(UNATTEND_DIR, exist_ok=True)


# ── Unattend XML ─────────────────────────────────────────────────────────────

def _server_xml(computer_name):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>100</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>2</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>2</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall><OSImage><InstallTo><DiskID>0</DiskID><PartitionID>2</PartitionID></InstallTo></OSImage></ImageInstall>
      <UserData><AcceptEula>true</AcceptEula></UserData>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <ComputerName>{computer_name}</ComputerName>
      <AutoLogon>
        <Username>Administrator</Username><Enabled>true</Enabled><LogonCount>99</LogonCount>
        <Password><Value>{ADMIN_PASS}</Value><PlainText>true</PlainText></Password>
      </AutoLogon>
      <UserAccounts>
        <AdministratorPassword><Value>{ADMIN_PASS}</Value><PlainText>true</PlainText></AdministratorPassword>
      </UserAccounts>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <NetworkLocation>Work</NetworkLocation>
        <ProtectYourPC>1</ProtectYourPC>
      </OOBE>
    </component>
  </settings>
</unattend>"""


def generate_unattend_files():
    create_unattend_directory()
    for vm_name in (ROUTER_VM, DC_VM, WORKSTATION_VM):
        path = os.path.join(UNATTEND_DIR, f"{vm_name}_autounattend.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_server_xml(vm_name))
        log.info(f"Unattend written: {path}")


# ── Build unattend ISO using pure PowerShell (no IMAPI2FS COM issues) ────────

def _build_unattend_iso_ps(xml_path: str, iso_out: str) -> str:
    """
    Returns a PowerShell snippet that builds a minimal ISO from xml_path → iso_out.
    Uses the .NET BinaryWriter approach — no IMAPI2FS COM dependency.
    The ISO has a single file 'autounattend.xml' at the root.
    """
    # Escape backslashes for PS string interpolation
    xml_ps  = xml_path.replace("\\", "\\\\")
    iso_ps  = iso_out.replace("\\", "\\\\")

    return f"""
# ── Build unattend ISO (pure .NET, no IMAPI2FS) ──────────────────────────
$xmlSrc  = "{xml_ps}"
$isoOut  = "{iso_ps}"

if (-not (Test-Path $xmlSrc)) {{
    Write-Warning "Unattend XML not found: $xmlSrc — skipping ISO"
}} else {{
    try {{
        # Read the source XML bytes
        $xmlBytes = [System.IO.File]::ReadAllBytes($xmlSrc)

        # ISO 9660 constants
        $sectorSize    = 2048
        $fileNameAscii = [System.Text.Encoding]::ASCII.GetBytes("AUTOUNATTEND.XML")
        $fileSectors   = [math]::Ceiling($xmlBytes.Length / $sectorSize)

        # Layout:
        #   Sector 0-15  : System area (blank)
        #   Sector 16    : Primary Volume Descriptor
        #   Sector 17    : Volume Descriptor Set Terminator
        #   Sector 18    : Path Table (L)
        #   Sector 19    : Path Table (M)
        #   Sector 20    : Root Directory Record
        #   Sector 21+   : File data

        $dataSector    = 21
        $totalSectors  = $dataSector + $fileSectors
        $totalBytes    = $totalSectors * $sectorSize

        $iso = New-Object byte[] $totalBytes

        # ── Helper: write bytes into $iso at offset ──────────────────────
        function Set-Bytes($arr, $offset, $data) {{
            for ($i = 0; $i -lt $data.Length; $i++) {{ $arr[$offset + $i] = $data[$i] }}
        }}
        function Set-String($arr, $offset, $str, $len) {{
            $b = [System.Text.Encoding]::ASCII.GetBytes($str.PadRight($len).Substring(0,$len))
            Set-Bytes $arr $offset $b
        }}
        function Set-U32L($arr, $offset, $val) {{   # little-endian uint32
            $arr[$offset]   = $val -band 0xFF
            $arr[$offset+1] = ($val -shr 8)  -band 0xFF
            $arr[$offset+2] = ($val -shr 16) -band 0xFF
            $arr[$offset+3] = ($val -shr 24) -band 0xFF
        }}
        function Set-U32B($arr, $offset, $val) {{   # big-endian uint32
            $arr[$offset]   = ($val -shr 24) -band 0xFF
            $arr[$offset+1] = ($val -shr 16) -band 0xFF
            $arr[$offset+2] = ($val -shr 8)  -band 0xFF
            $arr[$offset+3] = $val -band 0xFF
        }}
        function Set-U32BI($arr, $offset, $val) {{  # both-endian (8 bytes)
            Set-U32L $arr $offset       $val
            Set-U32B $arr ($offset + 4) $val
        }}
        function Set-U16BI($arr, $offset, $val) {{  # both-endian (4 bytes)
            $arr[$offset]   = $val -band 0xFF
            $arr[$offset+1] = ($val -shr 8) -band 0xFF
            $arr[$offset+2] = ($val -shr 8) -band 0xFF
            $arr[$offset+3] = $val -band 0xFF
        }}

        # ── Primary Volume Descriptor (sector 16) ────────────────────────
        $pvd = 16 * $sectorSize
        $iso[$pvd]      = 1      # type: primary
        Set-Bytes $iso ($pvd+1) ([System.Text.Encoding]::ASCII.GetBytes("CD001"))
        $iso[$pvd+6]    = 1      # version
        Set-String $iso ($pvd+8)  " " 32            # system id
        Set-String $iso ($pvd+40) "UNATTEND" 32     # volume id
        Set-U32BI  $iso ($pvd+80) $totalSectors      # volume space size
        Set-U16BI  $iso ($pvd+120) 1                 # volume set size
        Set-U16BI  $iso ($pvd+124) 1                 # volume sequence number
        Set-U16BI  $iso ($pvd+128) $sectorSize       # logical block size
        Set-U32BI  $iso ($pvd+132) 10                # path table size (minimal)
        Set-U32L   $iso ($pvd+140) 18                # L path table location
        Set-U32B   $iso ($pvd+148) 19                # M path table location

        # Root directory record in PVD (34 bytes at pvd+156)
        $rdOff = $pvd + 156
        $iso[$rdOff]     = 34    # record length
        $iso[$rdOff+1]   = 0     # extended attr length
        Set-U32BI $iso ($rdOff+2) 20          # location of root dir (sector 20)
        Set-U32BI $iso ($rdOff+10) $sectorSize # data length = 1 sector
        $iso[$rdOff+18]  = 0     # year (epoch)
        $iso[$rdOff+25]  = 0x02  # flags: directory
        $iso[$rdOff+32]  = 1     # file name length
        $iso[$rdOff+33]  = 0     # file name (root)

        Set-String $iso ($pvd+190) (Get-Date -Format "yyyyMMddHHmmss00") 16  # creation date
        $iso[$pvd+881]   = 1     # file structure version

        # ── Volume Descriptor Set Terminator (sector 17) ─────────────────
        $vdt = 17 * $sectorSize
        $iso[$vdt] = 0xFF
        Set-Bytes $iso ($vdt+1) ([System.Text.Encoding]::ASCII.GetBytes("CD001"))
        $iso[$vdt+6] = 1

        # ── Path Tables (sectors 18 & 19) — root only ────────────────────
        $pt = 18 * $sectorSize
        $iso[$pt]   = 1    # identifier length
        $iso[$pt+1] = 0    # extended attr
        Set-U32L $iso ($pt+2) 20  # location of root dir
        $iso[$pt+6] = 1    # parent dir number
        $iso[$pt+7] = 0    # identifier = root

        # Big-endian copy in sector 19
        $ptM = 19 * $sectorSize
        $iso[$ptM]   = 1
        $iso[$ptM+1] = 0
        Set-U32B $iso ($ptM+2) 20
        $iso[$ptM+6] = 0
        $iso[$ptM+7] = 1

        # ── Root Directory (sector 20) ────────────────────────────────────
        $dir = 20 * $sectorSize

        # "." self entry
        $iso[$dir]    = 34
        $iso[$dir+25] = 0x02
        Set-U32BI $iso ($dir+2) 20
        Set-U32BI $iso ($dir+10) $sectorSize
        $iso[$dir+32] = 1
        $iso[$dir+33] = 0

        # ".." parent entry
        $iso[$dir+34]    = 34
        $iso[$dir+34+25] = 0x02
        Set-U32BI $iso ($dir+34+2) 20
        Set-U32BI $iso ($dir+34+10) $sectorSize
        $iso[$dir+34+32] = 1
        $iso[$dir+34+33] = 1

        # File entry for autounattend.xml
        $fnLen  = $fileNameAscii.Length
        $feSize = 33 + $fnLen + (1 - ($fnLen % 2))   # must be even
        $fe     = $dir + 68
        $iso[$fe]      = [byte]$feSize
        $iso[$fe+1]    = 0
        Set-U32BI $iso ($fe+2)  $dataSector
        Set-U32BI $iso ($fe+10) $xmlBytes.Length
        $iso[$fe+25]   = 0       # flags: file
        $iso[$fe+32]   = [byte]$fnLen
        Set-Bytes $iso ($fe+33) $fileNameAscii

        # ── File data (sector 21+) ────────────────────────────────────────
        $dataOffset = $dataSector * $sectorSize
        Set-Bytes $iso $dataOffset $xmlBytes

        [System.IO.File]::WriteAllBytes($isoOut, $iso)
        Write-Output "Unattend ISO built: $isoOut"
    }} catch {{
        Write-Warning "Unattend ISO build failed: $_"
    }}
}}
# ── End unattend ISO build ────────────────────────────────────────────────
"""


# ── Switches ────────────────────────────────────────────────────────────────

def create_external_switch():
    ensure_vmms_running()
    ext = get_external_switch()

    # Check what already exists BEFORE creating anything
    existing_ext = run_ps(
        f'if (Get-VMSwitch -Name "{ext}" -ErrorAction SilentlyContinue) {{ "exists" }} else {{ "missing" }}',
        return_output=True
    )
    existing_int = run_ps(
        f'if (Get-VMSwitch -Name "{SWITCH_NAME}" -ErrorAction SilentlyContinue) {{ "exists" }} else {{ "missing" }}',
        return_output=True
    )

    switches_created = False

    if "missing" in (existing_ext or ""):
        ps_ext = f"""
$adapter = Get-NetAdapter | Where-Object {{$_.Status -eq "Up" -and $_.Virtual -eq $false}} |
    Sort-Object -Property LinkSpeed -Descending | Select-Object -First 1
if (-not $adapter) {{ throw "No physical network adapter found for external switch." }}
New-VMSwitch -Name "{ext}" -NetAdapterName $adapter.Name -AllowManagementOS $true
Write-Output "External switch created: {ext} (adapter: $($adapter.Name))"
"""
        run_ps(ps_ext, ignore_stderr=True)
        switches_created = True
        log.info(f"External switch created: {ext}")
    else:
        log.info(f"External switch exists: {ext}")

    # vmms loses its WMI handle after New-VMSwitch on many Windows versions.
    # Restart it now, before attempting the internal switch or any VM ops.
    if switches_created:
        log.info("[SWITCH] Restarting vmms to recover WMI handle after external switch creation...")
        run_ps("Restart-Service vmms -Force")
        time.sleep(8)
        ensure_vmms_running()

    if "missing" in (existing_int or ""):
        run_ps(f'New-VMSwitch -Name "{SWITCH_NAME}" -SwitchType Internal; Write-Output "Internal switch created: {SWITCH_NAME}"',
               ignore_stderr=True)
        log.info(f"Internal switch created: {SWITCH_NAME}")
        # Restart again after internal switch creation for same reason
        log.info("[SWITCH] Restarting vmms after internal switch creation...")
        run_ps("Restart-Service vmms -Force")
        time.sleep(8)
        ensure_vmms_running()
    else:
        log.info(f"Internal switch exists: {SWITCH_NAME}")


def configure_router_network():
    ensure_vmms_running()
    ext = get_external_switch()
    ps = f"""
$existing = Get-VMNetworkAdapter -VMName "{ROUTER_VM}" -ErrorAction SilentlyContinue |
    Where-Object {{$_.SwitchName -eq "{ext}"}}
if (-not $existing) {{
    Add-VMNetworkAdapter -VMName "{ROUTER_VM}" -SwitchName "{ext}" -Name "ExternalAdapter"
    Write-Output "External adapter added to {ROUTER_VM}"
}} else {{
    Write-Output "External adapter already present on {ROUTER_VM}"
}}
"""
    run_ps(ps)


# ── VM Creation ──────────────────────────────────────────────────────────────

def _cred_block():
    return f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)"""


def create_vm(vm: dict, retries: int = 3):
    """
    Create a single VM from a config dict.
    Retries up to `retries` times on Hyper-V transient failures,
    restarting vmms between each attempt.
    """
    name = vm["name"]

    for attempt in range(1, retries + 1):
        try:
            ensure_vmms_running()
            _create_vm_once(vm)
            return
        except Exception as e:
            log.warning(f"[VM] create_vm attempt {attempt}/{retries} failed for {name}: {e}")
            if attempt < retries:
                log.info(f"[VM] Restarting vmms and retrying in 10s...")
                try:
                    run_ps("Restart-Service vmms -Force; Start-Sleep 10")
                except Exception:
                    time.sleep(10)
            else:
                raise


def _create_vm_once(vm: dict):
    name = vm["name"]
    ram  = vm.get("ram_gb", 2) * 1024
    disk = vm.get("disk_gb", 60)
    gen  = vm.get("generation", 2)
    sw   = vm.get("network", SWITCH_NAME)
    role = vm.get("role", "")
    cpu  = vm.get("cpu", 1)

    if role in ("router", "domain_controller", "storage"):
        iso = SERVER_ISO
    elif role == "web":
        iso = get_win11_iso()  # placeholder; Ubuntu handled by linux_manager
    else:
        iso = WIN11_ISO

    vm_path  = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")
    os.makedirs(vm_path, exist_ok=True)

    if is_windows_installed(name):
        log.info(f"[SKIP] OS already installed on {name}")
        return

    unattend_xml = os.path.join(UNATTEND_DIR, f"{name}_autounattend.xml")
    iso_out      = os.path.join(vm_path, f"{name}_unattend.iso")

    # Build the unattend ISO snippet
    unattend_iso_ps = _build_unattend_iso_ps(unattend_xml, iso_out)

    # Escape paths for PS
    def ps_path(p): return p.replace("\\", "\\\\")

    ps = f"""
$vmName  = "{name}"
$vmPath  = "{ps_path(vm_path)}"
$vhdPath = "{ps_path(vhd_path)}"
$isoPath = "{ps_path(iso)}"

# ── Idempotency check ─────────────────────────────────────────────────────
if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) {{
    Write-Output "VM already exists: $vmName"
    exit 0
}}

# ── Create VHD ────────────────────────────────────────────────────────────
if (-not (Test-Path $vhdPath)) {{
    New-VHD -Path $vhdPath -SizeBytes {disk}GB -Dynamic -ErrorAction Stop
    Write-Output "VHD created: $vhdPath"
}}

# ── Create VM ────────────────────────────────────────────────────────────
New-VM -Name $vmName -MemoryStartupBytes {ram}MB -Generation {gen} `
    -VHDPath $vhdPath -Path $vmPath -SwitchName "{sw}" -ErrorAction Stop
Set-VMProcessor    -VMName $vmName -Count {cpu}
Set-VMMemory       -VMName $vmName -DynamicMemoryEnabled $false
Enable-VMIntegrationService -VMName $vmName -Name "Guest Service Interface" -ErrorAction SilentlyContinue

# ── Attach OS ISO ─────────────────────────────────────────────────────────
if (Get-VMDvdDrive -VMName $vmName -ErrorAction SilentlyContinue) {{
    Set-VMDvdDrive -VMName $vmName -Path $isoPath
}} else {{
    Add-VMDvdDrive -VMName $vmName -Path $isoPath
}}

# ── Set boot order (Gen 2 only) ───────────────────────────────────────────
if ({str(gen)} -eq 2) {{
    Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMDvdDrive -VMName $vmName)
    Set-VMFirmware -VMName $vmName -EnableSecureBoot Off
}}

Write-Output "VM created: $vmName"
"""
    run_ps(ps)

    # Build and attach unattend ISO (pure PS, no IMAPI2FS)
    run_ps(unattend_iso_ps + f"""
if (Test-Path "{ps_path(iso_out)}") {{
    Add-VMDvdDrive -VMName "{name}" -Path "{ps_path(iso_out)}" -ErrorAction SilentlyContinue
    Write-Output "Unattend ISO attached to {name}"
}}
""")

    # Additional data disks
    for i, size in enumerate(vm.get("additional_disks_gb", []), 1):
        dp = os.path.join(vm_path, f"{name}_data{i}.vhdx")
        dp_ps = ps_path(dp)
        run_ps(f"""
if (-not (Test-Path "{dp_ps}")) {{
    New-VHD -Path "{dp_ps}" -SizeBytes {size}GB -Dynamic
    Write-Output "Data disk created: {dp_ps}"
}}
if (Get-VM -Name "{name}" -ErrorAction SilentlyContinue) {{
    Add-VMHardDiskDrive -VMName "{name}" -Path "{dp_ps}"
    Write-Output "Data disk attached to {name}"
}}
""")


def create_router_vm():
    create_vm({"name": ROUTER_VM, "role": "router", "generation": 2,
               "cpu": 1, "ram_gb": 1, "disk_gb": 10, "network": SWITCH_NAME})


def create_domain_controller_vm():
    create_vm({"name": DC_VM, "role": "domain_controller", "generation": 2,
               "cpu": 2, "ram_gb": 4, "disk_gb": 120,
               "additional_disks_gb": [60, 60], "network": SWITCH_NAME})


def create_workstation_vm():
    create_vm({"name": WORKSTATION_VM, "role": "workstation", "generation": 2,
               "cpu": 1, "ram_gb": 2, "disk_gb": 60, "network": SWITCH_NAME})


# ── Install detection ────────────────────────────────────────────────────────

def is_windows_installed(vm_name: str) -> bool:
    """
    Mount the primary VHD and check for C:\\Windows\\System32.
    Returns True only when Windows is confirmed installed.
    """
    ps = f"""
$vm = Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue
if (-not $vm) {{ "False"; exit }}
$vhds = Get-VMHardDiskDrive -VMName "{vm_name}" -ErrorAction SilentlyContinue
if (-not $vhds) {{ "False"; exit }}
$vhd = $vhds[0].Path
if (-not (Test-Path $vhd)) {{ "False"; exit }}
try {{
    $m = Mount-VHD -Path $vhd -ReadOnly -Passthru -ErrorAction Stop
    $letter = ($m | Get-Disk | Get-Partition |
        Get-Volume | Where-Object {{ $_.FileSystemLabel -eq "Windows" }}).DriveLetter |
        Select-Object -First 1
    if ($letter -and (Test-Path "$($letter):\\Windows\\System32\\ntoskrnl.exe")) {{
        "True"
    }} else {{
        "False"
    }}
}} catch {{
    "False"
}} finally {{
    Dismount-VHD -Path $vhd -ErrorAction SilentlyContinue
}}
"""
    try:
        result = run_ps(ps, return_output=True)
        return bool(result) and result.strip().lower() == "true"
    except Exception:
        return False


# ── Wait for install (single VM) ─────────────────────────────────────────────

def wait_for_install(vm_name: str, timeout_minutes: int = 90, poll: int = 30) -> bool:
    deadline = time.time() + timeout_minutes * 60
    last     = None
    log.info(f"[WAIT] Monitoring OS install: {vm_name}")
    while time.time() < deadline:
        try:
            installed = is_windows_installed(vm_name)
        except Exception as e:
            log.warning(f"[WAIT] Detection error for {vm_name}: {e}")
            installed = False

        if installed != last:
            status = "INSTALLED ✅" if installed else "INSTALLING ⏳"
            log.info(f"[STATUS] {vm_name}: {status}")
            last = installed

        if installed:
            return True
        time.sleep(poll)

    raise TimeoutError(f"Timeout ({timeout_minutes}m) waiting for {vm_name} OS install")


wait_for_vm_install = wait_for_install   # alias


# ── Wait for ALL VMs in parallel ─────────────────────────────────────────────

def wait_for_all_installs(timeout_minutes: int = 90):
    """
    Wait for ROUTER_VM, DC_VM, and WORKSTATION_VM to finish installing
    in parallel using threads.  Raises the first error encountered.
    """
    vms = [ROUTER_VM, DC_VM, WORKSTATION_VM]
    log.info(f"[WAIT] Monitoring parallel OS installs: {vms}")

    errors = {}
    lock   = threading.Lock()

    def _wait(vm_name):
        try:
            wait_for_install(vm_name, timeout_minutes=timeout_minutes)
        except Exception as e:
            with lock:
                errors[vm_name] = e

    threads = [threading.Thread(target=_wait, args=(v,), daemon=True) for v in vms]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        msgs = "; ".join(f"{v}: {e}" for v, e in errors.items())
        raise RuntimeError(f"OS install failed: {msgs}")

    log.info("[WAIT] All VMs installed ✅")


# ── Start VMs ────────────────────────────────────────────────────────────────

def start_vm(name: str):
    ensure_vmms_running()
    log.info(f"Starting: {name}")
    run_ps(f"""
$vm = Get-VM -Name "{name}" -ErrorAction SilentlyContinue
if (-not $vm) {{ Write-Warning "VM not found: {name}"; exit }}
if ($vm.State -ne "Running") {{
    Start-VM -Name "{name}"
    Write-Output "Started: {name}"
}} else {{
    Write-Output "Already running: {name}"
}}
""")


def start_all_vms():
    for vm in (ROUTER_VM, DC_VM, WORKSTATION_VM):
        start_vm(vm)


# ── PowerShell Direct into VM ────────────────────────────────────────────────

def run_in_vm(vm_name: str, command: str, retries: int = 12, delay: int = 20):
    """
    Execute a PowerShell command inside the VM via Invoke-Command / PS Direct.
    Retries until the VM guest OS is ready to accept connections.
    """
    ps = f"""
{_cred_block()}
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}} -ErrorAction Stop
"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            run_ps(ps)
            return
        except Exception as e:
            last_err = e
            log.warning(f"[PSdirect {attempt}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} attempts: {last_err}")


run_command_in_vm = run_in_vm   # alias


def run_in_vm_output(vm_name: str, command: str, retries: int = 12, delay: int = 20) -> str:
    """Same as run_in_vm but returns stdout."""
    ps = f"""
{_cred_block()}
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}} -ErrorAction Stop
"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return run_ps(ps, return_output=True) or ""
        except Exception as e:
            last_err = e
            log.warning(f"[PSdirect {attempt}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} attempts: {last_err}")


# ── Post-install services ────────────────────────────────────────────────────

def install_active_directory():
    from config_loader import get_domain_config
    cfg      = get_domain_config()
    domain   = cfg["name"]
    netbios  = cfg["netbios"]
    safepass = cfg["safe_mode_password"]
    log.info(f"[AD] Installing Active Directory: {domain}")
    run_in_vm(DC_VM, f"""
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools
Import-Module ADDSDeployment
$sp = ConvertTo-SecureString "{safepass}" -AsPlainText -Force
Install-ADDSForest -DomainName "{domain}" -DomainNetbiosName "{netbios}" `
    -SafeModeAdministratorPassword $sp -InstallDNS -Force:$true -NoRebootOnCompletion:$false
""")


def configure_dhcp():
    from config_loader import get_dhcp_config
    d = get_dhcp_config()
    log.info("[DHCP] Configuring DHCP")
    run_in_vm(DC_VM, f"""
Install-WindowsFeature DHCP -IncludeManagementTools
Add-DhcpServerv4Scope -Name "{d.get('scope_name','AcmeBusiness')}" `
    -StartRange {d.get('start_ip','192.168.4.100')} `
    -EndRange   {d.get('end_ip','192.168.4.200')} `
    -SubnetMask {d.get('subnet_mask','255.255.255.0')}
Set-DhcpServerv4OptionValue -Router {d.get('router','192.168.4.1')} `
    -DnsServer {d.get('dns_server','192.168.4.3')} `
    -DnsDomain "{d.get('dns_domain','ad.acme.edu')}"
""")


def join_domain():
    from config_loader import get_domain_config
    domain = get_domain_config()["name"]
    log.info(f"[JOIN] Joining {WORKSTATION_VM} to {domain}")
    run_in_vm(WORKSTATION_VM, f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("{domain}\\Administrator", $sp)
Add-Computer -DomainName "{domain}" -Credential $cred -Force -Restart
""")
    wait_for_install(WORKSTATION_VM)


join_workstation_to_domain = join_domain   # alias


def verify_environment_post():
    log.info("[VERIFY] Post-install validation")
    checks = [
        ("Domain",  "Get-ADDomain"),
        ("DHCP",    "Get-DhcpServerv4Scope"),
        ("Users",   "Get-ADUser -Filter *"),
        ("Shares",  "Get-SmbShare"),
    ]
    for check_name, cmd in checks:
        try:
            run_in_vm(DC_VM, cmd)
            log.info(f"[PASS] {check_name}")
        except Exception as e:
            raise RuntimeError(f"[FAIL] {check_name}: {e}")