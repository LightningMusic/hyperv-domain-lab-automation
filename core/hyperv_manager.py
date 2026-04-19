"""
core/hyperv_manager.py
All paths, VM names, and credentials come from config_loader.
"""
import os, time
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


def _save_cp(step):
    os.makedirs(LAB_ROOT, exist_ok=True)
    open(CHECKPOINT_FILE, "w").write(step)

def _load_cp():
    return open(CHECKPOINT_FILE).read().strip() if os.path.exists(CHECKPOINT_FILE) else None

def run_step(step, func):
    if _load_cp() == step:
        log.info(f"[SKIP] {step}")
        return
    log.info(f"[RUN]  {step}")
    func()
    _save_cp(step)


# ── Validation ──────────────────────────────────────────────────────────────

def verify_environment():
    log.info("[VERIFY] Checking Hyper-V and ISOs")
    run_ps("""
$s = Get-Service vmms
if ($s.Status -ne 'Running') { Start-Service vmms; Start-Sleep 5 }
Write-Output "vmms: $($s.Status)"
""")
    run_ps("""
$f = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
if ($f.State -ne "Enabled") { throw "Hyper-V is not enabled." }
Write-Output "Hyper-V OK"
""")
    for iso in (SERVER_ISO, WIN11_ISO):
        if not os.path.exists(iso):
            raise FileNotFoundError(f"ISO not found: {iso}")
    log.info("[VERIFY] Environment OK")

verify_hyperv_installed = verify_environment   # alias used by environment_builder


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
        <Username>Administrator</Username><Enabled>true</Enabled><LogonCount>5</LogonCount>
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


# ── Switches ────────────────────────────────────────────────────────────────

def create_external_switch():
    ext = get_external_switch()
    ps = f"""
$ext = "{ext}"
$int = "{SWITCH_NAME}"
if (-not (Get-VMSwitch -Name $ext -ErrorAction SilentlyContinue)) {{
    $adapter = Get-NetAdapter | Where-Object {{$_.Status -eq "Up"}} | Select-Object -First 1
    if (-not $adapter) {{ throw "No active network adapter found for external switch." }}
    New-VMSwitch -Name $ext -NetAdapterName $adapter.Name -AllowManagementOS $true
    Write-Output "External switch created: $ext"
}} else {{ Write-Output "External switch exists: $ext" }}
if (-not (Get-VMSwitch -Name $int -ErrorAction SilentlyContinue)) {{
    New-VMSwitch -Name $int -SwitchType Internal
    Write-Output "Internal switch created: $int"
}} else {{ Write-Output "Internal switch exists: $int" }}
"""
    run_ps(ps)


def configure_router_network():
    ext = get_external_switch()
    ps = f"""
$existing = Get-VMNetworkAdapter -VMName "{ROUTER_VM}" |
    Where-Object {{$_.SwitchName -eq "{ext}"}}
if (-not $existing) {{
    Add-VMNetworkAdapter -VMName "{ROUTER_VM}" -SwitchName "{ext}" -Name "ExternalAdapter"
    Write-Output "External adapter added to {ROUTER_VM}"
}} else {{ Write-Output "External adapter already present" }}
"""
    run_ps(ps)


# ── VM Creation ──────────────────────────────────────────────────────────────

def _cred_block():
    return f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)"""


def create_vm(vm: dict):
    """Create a single VM from a vm config dict (used by vm_builder)."""
    name = vm["name"]
    ram  = vm.get("ram_gb", 2) * 1024
    disk = vm.get("disk_gb", 60)
    gen  = vm.get("generation", 2)
    sw   = vm.get("network", SWITCH_NAME)
    role = vm.get("role", "")
    iso  = SERVER_ISO if role in ("router", "domain_controller", "storage") else WIN11_ISO
    if role == "web":
        iso = get_win11_iso()   # Ubuntu handled separately; use server as placeholder

    vm_path  = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")
    os.makedirs(vm_path, exist_ok=True)

    if is_windows_installed(name):
        log.info(f"[SKIP] OS already on {name}")
        return

    unattend_xml = os.path.join(UNATTEND_DIR, f"{name}_autounattend.xml")

    ps = f"""
$vmName  = "{name}"
$vmPath  = "{vm_path}"
$vhdPath = "{vhd_path}"

if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) {{
    Write-Output "VM exists: $vmName"; exit
}}

New-VHD -Path $vhdPath -SizeBytes {disk}GB -Dynamic
New-VM -Name $vmName -MemoryStartupBytes {ram}MB -Generation {gen} `
    -VHDPath $vhdPath -Path $vmPath -SwitchName "{sw}"
Set-VMProcessor -VMName $vmName -Count {vm.get('cpu', 1)}
Enable-VMIntegrationService -VMName $vmName -Name "Guest Service Interface" -ErrorAction SilentlyContinue

if (Get-VMDvdDrive -VMName $vmName -ErrorAction SilentlyContinue) {{
    Set-VMDvdDrive -VMName $vmName -Path "{iso}"
}} else {{
    Add-VMDvdDrive -VMName $vmName -Path "{iso}"
}}

if ({gen} -eq 2) {{
    Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMDvdDrive -VMName $vmName)
}}

$xmlPath = "{unattend_xml}"
if (Test-Path $xmlPath) {{
    $isoOut = "$vmPath\\{name}_unattend.iso"
    try {{
        $fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
        $fsi.FileSystemsToCreate = 1
        $fsi.Root.AddFile("autounattend.xml", $xmlPath)
        $img = $fsi.CreateResultImage(); $stream = $img.ImageStream
        $file = [System.IO.File]::Create($isoOut)
        $buf  = New-Object byte[] 2048
        while (($n = $stream.Read($buf,0,$buf.Length)) -gt 0) {{ $file.Write($buf,0,$n) }}
        $file.Close()
        Add-VMDvdDrive -VMName $vmName -Path $isoOut
        Write-Output "Unattend ISO attached"
    }} catch {{ Write-Warning "Unattend ISO build failed: $_" }}
}}

Write-Output "VM created: $vmName"
"""
    run_ps(ps)

    # Additional disks
    for i, size in enumerate(vm.get("additional_disks_gb", []), 1):
        dp = os.path.join(vm_path, f"{name}_data{i}.vhdx")
        run_ps(f"""
if (-not (Test-Path "{dp}")) {{
    New-VHD -Path "{dp}" -SizeBytes {size}GB -Dynamic
    Add-VMHardDiskDrive -VMName "{name}" -Path "{dp}"
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

def is_windows_installed(vm_name):
    ps = f"""
$vm = Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue
if (-not $vm) {{ "False"; exit }}
$vhds = Get-VMHardDiskDrive -VMName "{vm_name}"
if (-not $vhds) {{ "False"; exit }}
$vhd = $vhds[0].Path
try {{
    $m = Mount-VHD -Path $vhd -Passthru -ErrorAction Stop
    $drive = ($m | Get-Disk | Get-Partition | Get-Volume |
        Where-Object {{$_.FileSystemLabel -eq "Windows"}}).DriveLetter
    if ($drive -and (Test-Path "$($drive):\\Windows\\System32")) {{ "True" }} else {{ "False" }}
}} catch {{ "False" }} finally {{ Dismount-VHD -Path $vhd -ErrorAction SilentlyContinue }}
"""
    result = run_ps(ps, return_output=True)
    return bool(result) and result.strip().lower() == "true"


def wait_for_install(vm_name, timeout_minutes=60, poll=20):
    """Alias: wait_for_vm_install. Used by environment_builder."""
    deadline = time.time() + timeout_minutes * 60
    last = None
    log.info(f"[WAIT] {vm_name} OS install...")
    while time.time() < deadline:
        try:
            installed = is_windows_installed(vm_name)
        except Exception as e:
            log.warning(f"Detection error {vm_name}: {e}")
            installed = False
        if installed != last:
            log.info(f"[STATUS] {vm_name}: {'INSTALLED ✅' if installed else 'INSTALLING ⏳'}")
            last = installed
        if installed:
            return True
        time.sleep(poll)
    raise TimeoutError(f"Timeout waiting for {vm_name} OS install")

wait_for_vm_install = wait_for_install   # second alias


def wait_for_all_installs():
    wait_for_install(ROUTER_VM)
    wait_for_install(DC_VM)
    wait_for_install(WORKSTATION_VM)


# ── Start VMs ────────────────────────────────────────────────────────────────

def start_vm(name: str):
    log.info(f"Starting: {name}")
    run_ps(f"""
if ((Get-VM -Name "{name}").State -ne "Running") {{
    Start-VM -Name "{name}"; Write-Output "Started: {name}"
}} else {{ Write-Output "Already running: {name}" }}
""")

def start_all_vms():
    for vm in (ROUTER_VM, DC_VM, WORKSTATION_VM):
        start_vm(vm)


# ── PowerShell Direct ────────────────────────────────────────────────────────

def run_in_vm(vm_name, command, retries=10, delay=15):
    ps = f"""
{_cred_block()}
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}}
"""
    for attempt in range(retries):
        try:
            run_ps(ps)
            return
        except Exception as e:
            log.warning(f"[RETRY {attempt+1}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} retries")

run_command_in_vm = run_in_vm   # alias


# ── Post-install services (used by environment_builder) ──────────────────────

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
    checks = [("Domain","Get-ADDomain"),("DHCP","Get-DhcpServerv4Scope"),
              ("Users","Get-ADUser -Filter *"),("Shares","Get-SmbShare")]
    for name, cmd in checks:
        try:
            run_in_vm(DC_VM, cmd)
            log.info(f"[PASS] {name}")
        except Exception as e:
            raise RuntimeError(f"[FAIL] {name}: {e}")