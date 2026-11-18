"""
core/hyperv_manager.py
Hyper-V VM lifecycle for the ACME lab.  All paths, names and credentials come
from config_loader.

Containment rules (see core/ownership.py):
  * The lab lives on a PRIVATE switch: no host vNIC, no host IP, no host NAT,
    nothing bridged to a physical adapter.
  * Only the router VM reaches the internet, through its own second NIC
    ("Uplink") on Hyper-V's built-in Default Switch.
  * Every VM and switch is tagged in its Notes field and recorded in
    state/manifest.json; objects that are not ours are never touched.
  * Every file lives under the project folder.
"""
import os
import time
import threading
from xml.sax.saxutils import escape as xml_escape

from config_loader import (
    get_lab_root, get_unattend_dir, get_server_iso, get_win11_iso,
    get_router_name, get_dc_name, get_workstation_name,
    get_internal_switch, get_uplink_switch_id, get_admin_password,
    get_vm_by_role, get_vms,
)
from core import ownership
from utils.powershell_runner import run_ps, run_ps_json
from utils.logger import get_logger

log = get_logger("hyperv_manager")

LAB_ROOT       = get_lab_root()
UNATTEND_DIR   = get_unattend_dir()
SERVER_ISO     = get_server_iso()
WIN11_ISO      = get_win11_iso()
SWITCH_NAME    = get_internal_switch()
UPLINK_ID      = get_uplink_switch_id()
ADMIN_PASS     = get_admin_password()
ROUTER_VM      = get_router_name()
DC_VM          = get_dc_name()
WORKSTATION_VM = get_workstation_name()

# The three VMs the core build stands up (PDC02 storage is wired in later).
CORE_VMS = (ROUTER_VM, DC_VM, WORKSTATION_VM)


# ── Validation ───────────────────────────────────────────────────────────────

def verify_environment():
    """Quick sanity check; the full read-only audit is core/preflight.py."""
    log.info("[VERIFY] Checking Hyper-V and install media")
    run_ps(r"""
$svc = Get-Service vmms -ErrorAction SilentlyContinue
if (-not $svc -or $svc.Status -ne 'Running') { throw "vmms (Hyper-V Virtual Machine Management) is not running." }
Write-Output "Hyper-V OK"
""", timeout=60)
    verify_iso_files()
    log.info("[VERIFY] Environment OK")

verify_hyperv_installed = verify_environment  # alias


def verify_iso_files():
    for iso in (SERVER_ISO, WIN11_ISO):
        if not os.path.exists(iso):
            raise FileNotFoundError(f"ISO not found: {iso}  (see install_media/README.md)")
    log.info("ISOs verified.")


def create_lab_directory():
    ownership.assert_inside_project(LAB_ROOT)
    os.makedirs(LAB_ROOT, exist_ok=True)
    log.info(f"Lab directory ready: {LAB_ROOT}")


def create_unattend_directory():
    ownership.assert_inside_project(UNATTEND_DIR)
    os.makedirs(UNATTEND_DIR, exist_ok=True)


# ── Per-role install profile ─────────────────────────────────────────────────

def _install_profile(role: str):
    """(iso, unattend flavor, edition index inside install.wim)."""
    if role == "router":                       # Server Core: minimal attack surface
        return SERVER_ISO, "server", 1         # idx 1 = Standard Evaluation (Core)
    if role in ("domain_controller", "storage"):
        return SERVER_ISO, "server", 2         # idx 2 = Standard Evaluation (Desktop Experience)
    if role == "workstation":
        return WIN11_ISO, "client", 1          # idx 1 = Windows 11 Enterprise Evaluation
    raise ValueError(f"Unknown VM role: {role!r}")


def _role_of(vm_name: str) -> str:
    for vm in get_vms():
        if vm["name"] == vm_name:
            return vm["role"]
    raise ValueError(f"VM not in config: {vm_name}")


# ── Unattend answer file ─────────────────────────────────────────────────────

def _unattend_xml(computer_name: str, image_index: int) -> str:
    """UEFI/GPT unattended install + local Administrator, no OOBE prompts."""
    pw    = xml_escape(ADMIN_PASS)
    wcm   = 'xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"'
    ident = 'processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"'
    return f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" {ident} {wcm}>
      <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
      <InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" {ident} {wcm}>
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>260</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>2</PartitionID></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>3</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>{image_index}</Value></MetaData></InstallFrom>
          <InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo>
        </OSImage>
      </ImageInstall>
      <UserData><AcceptEula>true</AcceptEula></UserData>
    </component>
  </settings>
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" {ident} {wcm}>
      <ComputerName>{computer_name}</ComputerName>
      <TimeZone>UTC</TimeZone>
    </component>
    <component name="Microsoft-Windows-Deployment" {ident} {wcm}>
      <RunSynchronous>
        <RunSynchronousCommand wcm:action="add"><Order>1</Order><Path>net user administrator /active:yes</Path></RunSynchronousCommand>
      </RunSynchronous>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-International-Core" {ident} {wcm}>
      <InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Shell-Setup" {ident} {wcm}>
      <UserAccounts>
        <AdministratorPassword><Value>{pw}</Value><PlainText>true</PlainText></AdministratorPassword>
      </UserAccounts>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <NetworkLocation>Work</NetworkLocation>
        <ProtectYourPC>3</ProtectYourPC>
        <SkipMachineOOBE>true</SkipMachineOOBE>
        <SkipUserOOBE>true</SkipUserOOBE>
      </OOBE>
    </component>
  </settings>
</unattend>
"""


def _unattend_path(vm_name: str) -> str:
    return os.path.join(UNATTEND_DIR, vm_name, "autounattend.xml")


def generate_unattend_files():
    """Write one answer file per core VM (the password is in them: gitignored, build-time only)."""
    create_unattend_directory()
    for vm in CORE_VMS:
        _, _, idx = _install_profile(_role_of(vm))
        path = _unattend_path(vm)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_unattend_xml(vm, idx))
        log.info(f"Unattend written: {path}")


# IMAPI2FS cannot hand a stream to PowerShell directly, so a tiny C# helper
# copies the image stream to disk.  The ISO carries Joliet names so Windows
# Setup finds a file called exactly 'autounattend.xml' at the root.
_BUILD_ISO_PS = r"""
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Runtime.InteropServices.ComTypes;
public static class AcmeIso {
    public static void Write(object stream, string path, int blockSize, int totalBlocks) {
        IStream s = (IStream)stream;
        byte[] buf = new byte[blockSize];
        using (FileStream fs = File.Create(path)) {
            for (int i = 0; i < totalBlocks; i++) {
                s.Read(buf, blockSize, IntPtr.Zero);
                fs.Write(buf, 0, blockSize);
            }
        }
    }
}
"@
$fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
$fsi.VolumeName = "UNATTEND"
$fsi.FileSystemsToCreate = 3          # ISO9660 + Joliet
$fsi.Root.AddTree("__STAGE_DIR__", $false)
$img = $fsi.CreateResultImage()
[AcmeIso]::Write($img.ImageStream, "__ISO_PATH__", $img.BlockSize, $img.TotalBlocks)
Write-Output "Unattend ISO built: __ISO_PATH__"
"""


def _build_unattend_iso(vm_name: str, iso_out: str):
    stage_dir = os.path.dirname(_unattend_path(vm_name))
    ownership.assert_inside_project(stage_dir)
    ownership.assert_inside_project(iso_out)
    run_ps(_BUILD_ISO_PS.replace("__STAGE_DIR__", stage_dir).replace("__ISO_PATH__", iso_out), timeout=120)


# ── Lab switch ───────────────────────────────────────────────────────────────

def _switch_record(name: str):
    return run_ps_json(
        f'Get-VMSwitch -Name "{name}" -ErrorAction SilentlyContinue | '
        f'Select-Object Name, @{{N="SwitchType";E={{"$($_.SwitchType)"}}}}, '
        f'@{{N="Owned";E={{{ownership.ps_owned()}}}}}',
        timeout=60)


def create_lab_switch():
    """Create the lab's PRIVATE switch (no host vNIC, no host IP)."""
    ownership.assert_switch_allowed(SWITCH_NAME)
    existing = _switch_record(SWITCH_NAME)
    if existing:
        if not existing.get("Owned"):
            raise ownership.OwnershipError(
                f"A switch named '{SWITCH_NAME}' already exists and is not owned by this lab; refusing to use it.")
        if existing.get("SwitchType") != "Private":
            raise ownership.OwnershipError(
                f"Switch '{SWITCH_NAME}' exists as {existing.get('SwitchType')}, not Private; "
                f"run 'destroy' and rebuild.")
        log.info(f"[SWITCH] Private switch exists: {SWITCH_NAME}")
        ownership.record("switch", SWITCH_NAME, type="Private")
        return
    log.info(f"[SWITCH] Creating PRIVATE switch: {SWITCH_NAME}")
    run_ps(f'New-VMSwitch -Name "{SWITCH_NAME}" -SwitchType Private -Notes "{ownership.note("switch")}" | Out-Null',
           timeout=120)
    ownership.record("switch", SWITCH_NAME, type="Private")
    log.info(f"[SWITCH] Created: {SWITCH_NAME}")


# ── VM creation ──────────────────────────────────────────────────────────────

def _vm_record(name: str):
    return run_ps_json(
        f'Get-VM -Name "{name}" -ErrorAction SilentlyContinue | '
        f'Select-Object Name, @{{N="State";E={{"$($_.State)"}}}}, '
        f'@{{N="Owned";E={{{ownership.ps_owned()}}}}}',
        timeout=60)


def _cred_block():
    return f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)"""


def _vm_has_matching_data_disk(name: str, disk_prefix: str) -> bool:
    ps = f"""
$match = Get-VMHardDiskDrive -VMName "{name}" -ErrorAction SilentlyContinue |
    Where-Object {{ [System.IO.Path]::GetFileName($_.Path).StartsWith("{disk_prefix}", [System.StringComparison]::OrdinalIgnoreCase) }} |
    Select-Object -First 1
if ($match) {{ "True" }} else {{ "False" }}
"""
    out = run_ps(ps, return_output=True, timeout=60) or "False"
    return "True" in out


def _ensure_vhd_file(disk_path: str, size_gb: int):
    ownership.assert_inside_project(disk_path)
    run_ps(f"""
$diskPath = "{disk_path}"
if (-not (Test-Path $diskPath)) {{
    New-VHD -Path $diskPath -SizeBytes {size_gb}GB -Dynamic | Out-Null
    Write-Output "Disk created: $diskPath"
}} else {{
    Write-Output "Disk file exists: $diskPath"
}}
""", timeout=120)


def _attach_vm_disk(name: str, disk_path: str):
    run_ps(f"""
$vmName = "{name}"
$diskPath = "{disk_path}"

if (-not (Get-VM -Name $vmName -ErrorAction SilentlyContinue)) {{
    throw "VM not found: $vmName"
}}

$existing = Get-VMHardDiskDrive -VMName $vmName -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Path -eq $diskPath }} |
    Select-Object -First 1
if ($existing) {{
    Write-Output "Disk already attached: $diskPath"
    exit
}}

$lastError = $null
for ($attempt = 1; $attempt -le 5; $attempt++) {{
    try {{
        Add-VMHardDiskDrive -VMName $vmName -Path $diskPath -ErrorAction Stop
        Write-Output "Disk attached: $diskPath"
        exit
    }} catch {{
        $lastError = $_

        $attachedNow = Get-VMHardDiskDrive -VMName $vmName -ErrorAction SilentlyContinue |
            Where-Object {{ $_.Path -eq $diskPath }} |
            Select-Object -First 1
        if ($attachedNow) {{
            Write-Output "Disk already attached after retry: $diskPath"
            exit
        }}

        if ($attempt -eq 5) {{
            throw
        }}

        Start-Sleep -Seconds (2 * $attempt)
    }}
}}

throw $lastError
""", timeout=180)


def _ensure_vm_data_disk(name: str, disk_path: str, size_gb: int):
    disk_dir = os.path.dirname(disk_path)
    disk_name = os.path.basename(disk_path)
    disk_stem, disk_ext = os.path.splitext(disk_name)

    if _vm_has_matching_data_disk(name, disk_stem):
        log.info(f"[VM] Matching data disk already attached for {name}: {disk_stem}")
        return

    candidates = [disk_path]
    for i in range(1, 6):
        candidates.append(os.path.join(disk_dir, f"{disk_stem}_retry{i}{disk_ext}"))

    last_error = None
    for candidate in candidates:
        if _vm_has_matching_data_disk(name, disk_stem):
            log.info(f"[VM] Matching data disk already attached for {name}: {disk_stem}")
            return

        _ensure_vhd_file(candidate, size_gb)
        try:
            _attach_vm_disk(name, candidate)
            if candidate != disk_path:
                log.warning(f"[VM] Attached recovery disk for {name}: {candidate}")
            return
        except RuntimeError as exc:
            last_error = exc
            msg = str(exc)
            is_lock_error = "0x80070020" in msg or "being used by another process" in msg
            if not is_lock_error:
                raise
            log.warning(f"[VM] Disk path locked for {name}, trying next candidate: {candidate}")

    raise RuntimeError(f"Unable to attach any data disk for {name}. Last error: {last_error}")


def create_vm(vm: dict):
    """
    Create one Gen2 VM on the lab's private switch, tagged and recorded.
    Idempotent: an existing VM that carries our tag is left alone; one that
    does not is never touched (OwnershipError).
    """
    name = vm["name"]
    ownership.assert_vm_allowed(name)

    existing = _vm_record(name)
    if existing:
        if not existing.get("Owned"):
            raise ownership.OwnershipError(
                f"A VM named '{name}' already exists and is not owned by this lab; refusing to touch it.")
        log.info(f"[SKIP] VM already exists (ours): {name}")
        return

    role = vm.get("role", "")
    iso, flavor, _ = _install_profile(role)
    ram  = int(vm.get("ram_gb", 2)) * 1024
    disk = int(vm.get("disk_gb", 60))
    cpu  = int(vm.get("cpu", 1))
    sw   = vm.get("network", SWITCH_NAME)

    vm_path  = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")
    iso_out  = os.path.join(vm_path, f"{name}_unattend.iso")
    ownership.assert_inside_project(vm_path)
    os.makedirs(vm_path, exist_ok=True)

    if not os.path.exists(_unattend_path(name)):
        generate_unattend_files()
    _build_unattend_iso(name, iso_out)

    router_nic = ""
    if role == "router":
        router_nic = f"""
$uplink = Get-VMSwitch -Id "{UPLINK_ID}" -ErrorAction Stop
Add-VMNetworkAdapter -VMName $vmName -Name "Uplink" -SwitchName $uplink.Name
Set-VMNetworkAdapter -VMName $vmName -Name "Uplink" -DeviceNaming On
"""
    tpm = ""
    if flavor == "client":      # Windows 11 requires Secure Boot + TPM 2.0
        tpm = """
Set-VMKeyProtector -VMName $vmName -NewLocalKeyProtector
Enable-VMTPM -VMName $vmName
"""

    ps = f"""
$vmName  = "{name}"
$vmPath  = "{vm_path}"
$vhdPath = "{vhd_path}"

New-VHD -Path $vhdPath -SizeBytes {disk}GB -Dynamic | Out-Null
New-VM -Name $vmName -MemoryStartupBytes {ram}MB -Generation 2 `
    -VHDPath $vhdPath -Path $vmPath -SwitchName "{sw}" | Out-Null
Set-VM -Name $vmName -Notes "{ownership.note('vm')}" -AutomaticCheckpointsEnabled $false
Set-VMProcessor -VMName $vmName -Count {cpu}
Rename-VMNetworkAdapter -VMName $vmName -Name "Network Adapter" -NewName "Lab"
Set-VMNetworkAdapter -VMName $vmName -Name "Lab" -DeviceNaming On
Enable-VMIntegrationService -VMName $vmName -Name "Guest Service Interface"
{router_nic}{tpm}
# Install media first (boot device), answer-file ISO second
Add-VMDvdDrive -VMName $vmName -Path "{iso}"
$boot = Get-VMDvdDrive -VMName $vmName | Where-Object {{ $_.Path -ieq "{iso}" }} | Select-Object -First 1
Set-VMFirmware -VMName $vmName -FirstBootDevice $boot
Add-VMDvdDrive -VMName $vmName -Path "{iso_out}"
Write-Output "VM created: $vmName"
"""
    run_ps(ps, timeout=300)
    ownership.record("vm", name, path=vm_path, vhd=vhd_path, role=role)

    for i, size in enumerate(vm.get("additional_disks_gb", []), 1):
        dp = os.path.join(vm_path, f"{name}_data{i}.vhdx")
        _ensure_vm_data_disk(name, dp, size)


def create_router_vm():
    create_vm(get_vm_by_role("router"))

def create_domain_controller_vm():
    create_vm(get_vm_by_role("domain_controller"))

def create_workstation_vm():
    create_vm(get_vm_by_role("workstation"))


# ── Start VMs ─────────────────────────────────────────────────────────────────

def _send_boot_keypress(vm_name: str, seconds: int = 20):
    """
    Gen2 Windows media boots through 'Press any key to boot from CD or DVD'.
    On an unattended VM nobody is there to press it, so the VM would fall
    through to the empty disk and never install.  Send Space through the
    Hyper-V keyboard for a few seconds right after power-on.
    """
    run_ps(f"""
$vm = Get-CimInstance -Namespace root\\virtualization\\v2 -ClassName Msvm_ComputerSystem -Filter "ElementName='{vm_name}'"
$kb = Get-CimAssociatedInstance -InputObject $vm -ResultClassName Msvm_Keyboard
$end = (Get-Date).AddSeconds({seconds})
while ((Get-Date) -lt $end) {{
    Invoke-CimMethod -InputObject $kb -MethodName TypeKey -Arguments @{{ keyCode = [uint32]32 }} | Out-Null
    Start-Sleep -Milliseconds 500
}}
""", timeout=seconds + 60)


def start_vm(name: str, first_boot: bool = False):
    ownership.assert_vm_allowed(name)
    rec = _vm_record(name)
    if not rec:
        raise RuntimeError(f"VM not found: {name}")
    if not rec.get("Owned"):
        raise ownership.OwnershipError(f"VM '{name}' is not owned by this lab; refusing to start it.")
    if rec.get("State") == "Running":
        log.info(f"Already running: {name}")
        return
    log.info(f"Starting: {name}")
    run_ps(f'Start-VM -Name "{name}"', timeout=120)
    if first_boot:
        _send_boot_keypress(name)


def start_all_vms(first_boot: bool = True):
    for vm in CORE_VMS:
        start_vm(vm, first_boot=first_boot)


# ── PowerShell Direct ─────────────────────────────────────────────────────────
# PowerShell Direct talks to the guest over VMBus: it needs no network, which is
# what lets the lab stay on a private switch.

def _direct_script(vm_name: str, command: str) -> str:
    return f"""
{_cred_block()}
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}} -ErrorAction Stop
"""


def run_in_vm(vm_name: str, command: str, retries: int = 12, delay: int = 20):
    ps = _direct_script(vm_name, command)
    for attempt in range(1, retries + 1):
        try:
            run_ps(ps); return
        except Exception as e:
            log.warning(f"[PSdirect {attempt}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} retries")

run_command_in_vm = run_in_vm  # alias


def run_in_vm_output(vm_name: str, command: str, retries: int = 12, delay: int = 20) -> str:
    ps = _direct_script(vm_name, command)
    for attempt in range(1, retries + 1):
        try:
            return run_ps(ps, return_output=True) or ""
        except Exception as e:
            log.warning(f"[PSdirect {attempt}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} retries")


# ── Install detection ─────────────────────────────────────────────────────────
# The only reliable "install finished" signal is the guest itself: once
# PowerShell Direct answers with the computer name set by the unattend file,
# Setup, specialize and OOBE are all done.

def is_windows_installed(vm_name: str) -> bool:
    rec = _vm_record(vm_name)
    if not rec or rec.get("State") != "Running":
        return False
    try:
        out = run_ps(_direct_script(vm_name, "$env:COMPUTERNAME"), return_output=True, timeout=60)
        return bool(out) and out.strip().lower() == vm_name.lower()
    except Exception:
        return False


def wait_for_install(vm_name: str, timeout_minutes: int = 120, poll: int = 30) -> bool:
    deadline = time.time() + timeout_minutes * 60
    last     = None
    log.info(f"[WAIT] Monitoring OS install: {vm_name} (timeout: {timeout_minutes}m)")

    while time.time() < deadline:
        try:
            installed = is_windows_installed(vm_name)
        except Exception as e:
            log.warning(f"[WAIT] Detection error {vm_name}: {e}")
            installed = False

        if installed != last:
            log.info(f"[STATUS] {vm_name}: {'INSTALLED' if installed else 'INSTALLING'}")
            last = installed

        if installed:
            return True
        time.sleep(poll)

    raise TimeoutError(f"Timeout ({timeout_minutes}m) waiting for {vm_name} OS install")

wait_for_vm_install = wait_for_install  # alias


def wait_for_all_installs(timeout_minutes: int = 120):
    """Wait for all core VMs to finish OS install in parallel."""
    vms    = list(CORE_VMS)
    errors = {}
    lock   = threading.Lock()

    def _wait(vm_name):
        try:
            wait_for_install(vm_name, timeout_minutes=timeout_minutes)
        except Exception as e:
            with lock:
                errors[vm_name] = e

    log.info(f"[WAIT] Monitoring parallel OS installs: {vms}")
    threads = [threading.Thread(target=_wait, args=(v,), daemon=True) for v in vms]
    for t in threads: t.start()
    for t in threads: t.join()

    if errors:
        msgs = "; ".join(f"{v}: {e}" for v, e in errors.items())
        raise RuntimeError(f"OS install failed: {msgs}")
    log.info("[WAIT] All VMs installed")


# ── Post-install services ─────────────────────────────────────────────────────

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

join_workstation_to_domain = join_domain  # alias


def verify_environment_post():
    log.info("[VERIFY] Post-install validation")
    checks = [("Domain","Get-ADDomain"),("DHCP","Get-DhcpServerv4Scope"),
              ("Users","Get-ADUser -Filter *"),("Shares","Get-SmbShare")]
    for name, cmd in checks:
        try:
            run_in_vm(DC_VM, cmd)
            log.info(f"[PASS] {name}")
        except Exception as e:
            raise RuntimeError(f"[FAIL] {name}: {e}")
