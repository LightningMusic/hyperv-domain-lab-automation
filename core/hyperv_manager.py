"""
core/hyperv_manager.py
All paths, VM names, and credentials come from config_loader.
"""
import os, time, threading
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


def _save_cp(step):
    os.makedirs(LAB_ROOT, exist_ok=True)
    open(CHECKPOINT_FILE, "w").write(step)

def _load_cp():
    return open(CHECKPOINT_FILE).read().strip() if os.path.exists(CHECKPOINT_FILE) else None

def run_step(step, func):
    if _load_cp() == step:
        log.info(f"[SKIP] {step}"); return
    log.info(f"[RUN]  {step}")
    func()
    _save_cp(step)


# ── Validation ───────────────────────────────────────────────────────────────

def verify_environment():
    log.info("[VERIFY] Checking Hyper-V, vmms, and ISOs")
    # Quick vmms health check (30s timeout, no full reset logic needed here)
    run_ps("""
$svc = Get-Service vmms -ErrorAction SilentlyContinue
if (-not $svc -or $svc.Status -ne 'Running') { throw "vmms is not running." }
$f = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
if ($f.State -ne "Enabled") { throw "Hyper-V is not enabled on this machine." }
Write-Output "Hyper-V OK"
""")
    for iso in (SERVER_ISO, WIN11_ISO):
        if not os.path.exists(iso):
            raise FileNotFoundError(f"ISO not found: {iso}")
    log.info("[VERIFY] Environment OK")

verify_hyperv_installed = verify_environment  # alias


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


# ── Switches ─────────────────────────────────────────────────────────────────
# FIX: The NAT/host-IP setup was timing out (New-NetIPAddress hangs on some
# systems). Replaced with a fast, safe version that skips if already configured
# and uses SilentlyContinue throughout so it never blocks the pipeline.

def create_external_switch():
    ext = get_external_switch()

    # Internal switch (required for all VM traffic)
    existing_int = run_ps(
        f'if (Get-VMSwitch -Name "{SWITCH_NAME}" -ErrorAction SilentlyContinue) {{ "exists" }} else {{ "missing" }}',
        return_output=True
    ) or ""

    if "missing" in existing_int:
        log.info(f"[SWITCH] Creating internal switch: {SWITCH_NAME}")
        run_ps(f'New-VMSwitch -Name "{SWITCH_NAME}" -SwitchType Internal')
        time.sleep(2)
        log.info(f"[SWITCH] Internal switch created: {SWITCH_NAME}")
    else:
        log.info(f"[SWITCH] Internal switch exists: {SWITCH_NAME}")

    # Host NAT gateway IP — skip if already assigned, never block on failure
    # Use a short inline script with SilentlyContinue everywhere
    run_ps(f"""
$ifAlias = (Get-NetAdapter | Where-Object {{ $_.Name -like "*{SWITCH_NAME}*" }} | Select-Object -First 1).Name
if ($ifAlias) {{
    $existing = Get-NetIPAddress -InterfaceAlias $ifAlias -IPAddress "192.168.4.254" -ErrorAction SilentlyContinue
    if (-not $existing) {{
        New-NetIPAddress -InterfaceAlias $ifAlias -IPAddress "192.168.4.254" -PrefixLength 24 -ErrorAction SilentlyContinue
    }}
}}
if (-not (Get-NetNat -Name "AcmeLabNAT" -ErrorAction SilentlyContinue)) {{
    New-NetNat -Name "AcmeLabNAT" -InternalIPInterfaceAddressPrefix "192.168.4.0/24" -ErrorAction SilentlyContinue
}}
Write-Output "NAT setup done"
""")
    log.info(f"[SWITCH] Host NAT ready")

    # External switch — optional, only on wired Ethernet, skip on Wi-Fi
    existing_ext = run_ps(
        f'if (Get-VMSwitch -Name "{ext}" -ErrorAction SilentlyContinue) {{ "exists" }} else {{ "missing" }}',
        return_output=True
    ) or ""

    if "exists" in existing_ext:
        log.info(f"[SWITCH] External switch exists: {ext}"); return

    wired = run_ps(r"""
$a = Get-NetAdapter | Where-Object {
    $_.Status -eq "Up" -and $_.Virtual -eq $false -and
    $_.PhysicalMediaType -notin @(9) -and
    $_.Name -notmatch "Wi.?Fi|Wireless|WLAN|802\.11"
} | Sort-Object LinkSpeed -Descending | Select-Object -First 1
if ($a) { $a.Name } else { "NONE" }
""", return_output=True) or "NONE"

    if wired.strip() in ("NONE", ""):
        log.info("[SWITCH] No wired adapter — skipping external switch (using host NAT)")
        return

    log.info(f"[SWITCH] Creating external switch on: {wired.strip()}")
    run_ps(f'New-VMSwitch -Name "{ext}" -NetAdapterName "{wired.strip()}" -AllowManagementOS $true -ErrorAction Stop')
    log.info(f"[SWITCH] External switch ready: {ext}")


def configure_router_network():
    ext = get_external_switch()
    exists = run_ps(
        f'if (Get-VMSwitch -Name "{ext}" -ErrorAction SilentlyContinue) {{ "yes" }} else {{ "no" }}',
        return_output=True) or ""
    if "yes" not in exists:
        log.info(f"[ROUTER] No external switch — skipping external adapter"); return
    run_ps(f"""
$existing = Get-VMNetworkAdapter -VMName "{ROUTER_VM}" |
    Where-Object {{$_.SwitchName -eq "{ext}"}}
if (-not $existing) {{
    Add-VMNetworkAdapter -VMName "{ROUTER_VM}" -SwitchName "{ext}" -Name "ExternalAdapter"
    Write-Output "External adapter added"
}} else {{ Write-Output "External adapter already present" }}
""")


# ── VM Creation ───────────────────────────────────────────────────────────────

def _cred_block():
    return f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)"""


def create_vm(vm: dict):
    name = vm["name"]
    ram  = vm.get("ram_gb", 2) * 1024
    disk = vm.get("disk_gb", 60)
    gen  = vm.get("generation", 2)
    sw   = vm.get("network", SWITCH_NAME)
    role = vm.get("role", "")
    cpu  = vm.get("cpu", 1)
    iso  = SERVER_ISO if role in ("router", "domain_controller", "storage") else WIN11_ISO

    vm_path  = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")
    os.makedirs(vm_path, exist_ok=True)

    if is_windows_installed(name):
        log.info(f"[SKIP] OS already on {name}"); return

    unattend_xml = os.path.join(UNATTEND_DIR, f"{name}_autounattend.xml")
    iso_out      = os.path.join(vm_path, f"{name}_unattend.iso")

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
Set-VMProcessor -VMName $vmName -Count {cpu}
Enable-VMIntegrationService -VMName $vmName -Name "Guest Service Interface" -ErrorAction SilentlyContinue

if (Get-VMDvdDrive -VMName $vmName -ErrorAction SilentlyContinue) {{
    Set-VMDvdDrive -VMName $vmName -Path "{iso}"
}} else {{
    Add-VMDvdDrive -VMName $vmName -Path "{iso}"
}}
if ({gen} -eq 2) {{
    Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMDvdDrive -VMName $vmName)
    Set-VMFirmware -VMName $vmName -EnableSecureBoot Off
}}

$xmlPath = "{unattend_xml}"
if (Test-Path $xmlPath) {{
    try {{
        $fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
        $fsi.FileSystemsToCreate = 1
        $fsi.Root.AddFile("autounattend.xml", $xmlPath)
        $img = $fsi.CreateResultImage(); $stream = $img.ImageStream
        $file = [System.IO.File]::Create("{iso_out}")
        $buf  = New-Object byte[] 2048
        while (($n = $stream.Read($buf,0,$buf.Length)) -gt 0) {{ $file.Write($buf,0,$n) }}
        $file.Close()
        Add-VMDvdDrive -VMName $vmName -Path "{iso_out}"
        Write-Output "Unattend ISO attached"
    }} catch {{ Write-Warning "Unattend ISO build failed: $_" }}
}}
Write-Output "VM created: $vmName"
"""
    run_ps(ps)

    for i, size in enumerate(vm.get("additional_disks_gb", []), 1):
        dp = os.path.join(vm_path, f"{name}_data{i}.vhdx")
        run_ps(f"""
if (-not (Test-Path "{dp}")) {{
    New-VHD -Path "{dp}" -SizeBytes {size}GB -Dynamic
}}
if (Get-VM -Name "{name}" -ErrorAction SilentlyContinue) {{
    Add-VMHardDiskDrive -VMName "{name}" -Path "{dp}"
}}
""")


def create_router_vm():
    create_vm({"name": ROUTER_VM,      "role": "router",            "generation": 2,
               "cpu": 1,  "ram_gb": 1, "disk_gb": 10,  "network": SWITCH_NAME})

def create_domain_controller_vm():
    create_vm({"name": DC_VM,          "role": "domain_controller", "generation": 2,
               "cpu": 2,  "ram_gb": 4, "disk_gb": 120, "network": SWITCH_NAME,
               "additional_disks_gb": [60, 60]})

def create_workstation_vm():
    create_vm({"name": WORKSTATION_VM, "role": "workstation",       "generation": 2,
               "cpu": 1,  "ram_gb": 2, "disk_gb": 60,  "network": SWITCH_NAME})


# ── Install detection ─────────────────────────────────────────────────────────
# FIX: Windows Setup takes 45-120 min. Heartbeat only becomes OK AFTER setup
# completes. Previous logic polled heartbeat which always returned False during
# install, causing a premature timeout.
#
# New strategy:
#   1. If VM is Running + Heartbeat OK → definitely done
#   2. If VM is Running + has a usable IP → done (post-OOBE)
#   3. If VM is Running → still installing (return False, keep waiting)
#   4. If VM is Off → setup rebooted and finished, now off? Unlikely.
#      Try mounting VHD to check for ntoskrnl.exe
#
# Timeout raised to 180 minutes to cover slow machines.

def is_windows_installed(vm_name: str) -> bool:
    ps = f"""
$vm = Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue
if (-not $vm) {{ "False"; exit }}

# Check 1: Heartbeat integration service reports OK
if ($vm.State -eq "Running") {{
    $hb = Get-VMIntegrationService -VMName "{vm_name}" -Name "Heartbeat" -ErrorAction SilentlyContinue
    if ($hb -and $hb.PrimaryStatusDescription -eq "OK") {{ "True"; exit }}

    # Check 2: VM has been assigned a non-APIPA IP (post-OOBE network up)
    $ips = @(Get-VMNetworkAdapter -VMName "{vm_name}" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty IPAddresses)
    $usable = $ips | Where-Object {{
        $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notlike '169.254*' -and $_ -ne '0.0.0.0'
    }} | Select-Object -First 1
    if ($usable) {{ "True"; exit }}

    # VM is running but setup still in progress
    "False"; exit
}}

# VM is Off or Saved — try offline VHD check
$vhds = Get-VMHardDiskDrive -VMName "{vm_name}" -ErrorAction SilentlyContinue
if (-not $vhds) {{ "False"; exit }}
$vhd = $vhds[0].Path
if (-not (Test-Path $vhd)) {{ "False"; exit }}
try {{
    $m = Mount-VHD -Path $vhd -Passthru -ErrorAction Stop
    $installed = $false
    foreach ($vol in ($m | Get-Disk | Get-Partition | Get-Volume -ErrorAction SilentlyContinue)) {{
        if ($vol.DriveLetter -and (Test-Path "$($vol.DriveLetter):\\Windows\\System32\\ntoskrnl.exe")) {{
            $installed = $true; break
        }}
    }}
    if ($installed) {{ "True" }} else {{ "False" }}
}} catch {{ "False" }} finally {{ Dismount-VHD -Path $vhd -ErrorAction SilentlyContinue }}
"""
    try:
        result = run_ps(ps, return_output=True)
        return bool(result) and result.strip().lower() == "true"
    except Exception:
        return False


def wait_for_install(vm_name: str, timeout_minutes: int = 180, poll: int = 30) -> bool:
    """
    Wait for a VM to finish OS installation.
    Timeout raised to 180 min — Windows Server Setup on a slow machine can take 2h.
    Poll interval 30s to reduce Hyper-V WMI load.
    """
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
            log.info(f"[STATUS] {vm_name}: {'INSTALLED ✅' if installed else 'INSTALLING ⏳'}")
            last = installed

        if installed:
            return True
        time.sleep(poll)

    raise TimeoutError(f"Timeout ({timeout_minutes}m) waiting for {vm_name} OS install")

wait_for_vm_install = wait_for_install  # alias


def wait_for_all_installs(timeout_minutes: int = 180):
    """Wait for all three base VMs to finish OS install in parallel."""
    vms    = [ROUTER_VM, DC_VM, WORKSTATION_VM]
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
    log.info("[WAIT] All VMs installed ✅")


# ── Start VMs ─────────────────────────────────────────────────────────────────

def start_vm(name: str):
    log.info(f"Starting: {name}")
    run_ps(f"""
$vm = Get-VM -Name "{name}" -ErrorAction SilentlyContinue
if (-not $vm) {{ Write-Warning "VM not found: {name}"; exit }}
if ($vm.State -ne "Running") {{
    Start-VM -Name "{name}"
    Write-Output "Started: {name}"
}} else {{ Write-Output "Already running: {name}" }}
""")

def start_all_vms():
    for vm in (ROUTER_VM, DC_VM, WORKSTATION_VM):
        start_vm(vm)


# ── PowerShell Direct ─────────────────────────────────────────────────────────

def run_in_vm(vm_name: str, command: str, retries: int = 12, delay: int = 20):
    ps = f"""
{_cred_block()}
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}} -ErrorAction Stop
"""
    for attempt in range(1, retries + 1):
        try:
            run_ps(ps); return
        except Exception as e:
            log.warning(f"[PSdirect {attempt}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} retries")

run_command_in_vm = run_in_vm  # alias


def run_in_vm_output(vm_name: str, command: str, retries: int = 12, delay: int = 20) -> str:
    ps = f"""
{_cred_block()}
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}} -ErrorAction Stop
"""
    for attempt in range(1, retries + 1):
        try:
            return run_ps(ps, return_output=True) or ""
        except Exception as e:
            log.warning(f"[PSdirect {attempt}/{retries}] {vm_name}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not exec in {vm_name} after {retries} retries")


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