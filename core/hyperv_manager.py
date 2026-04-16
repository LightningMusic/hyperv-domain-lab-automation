import os
from utils.powershell_runner import run_ps

LAB_ROOT = r"C:\CVNP-Python\Python Projects\Lab Deployment\LabVMs"

SERVER_ISO = r"C:\CVNP-Python\Python Projects\Lab Deployment\install_media\SERVER_EVAL_x64FRE_en-us.iso"
WIN11_ISO = r"C:\CVNP-Python\Python Projects\Lab Deployment\install_media\Windows_11_Eval.iso"

SWITCH_NAME = vm_config["network"]

ROUTER_VM = "ACME-Router"
DC_VM = "ACME-DC01"
WORKSTATION_VM = "ACME-WKS01"

UNATTEND_DIR = r"C:\CVNP-Python\Python Projects\Lab Deployment\temp_unattend"

ROUTER_UNATTEND = os.path.join(UNATTEND_DIR, "router_autounattend.xml")
DC_UNATTEND = os.path.join(UNATTEND_DIR, "dc_autounattend.xml")
WORKSTATION_UNATTEND = os.path.join(UNATTEND_DIR, "workstation_autounattend.xml")

CHECKPOINT_FILE = os.path.join(LAB_ROOT, "deployment_state.txt")

# ------------------------------------------------
# Checkpoint Helpers
# ------------------------------------------------

def run_step(step_name, func):
    current = load_checkpoint()

    if current == step_name:
        print(f"[SKIP] {step_name} already completed")
        return

    print(f"[RUN] {step_name}")
    func()
    save_checkpoint(step_name)


def save_checkpoint(step):
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(step)


def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return None
    with open(CHECKPOINT_FILE, "r") as f:
        return f.read().strip()


# ------------------------------------------------
# Environment Validation
# ------------------------------------------------

def verify_hyperv_installed():
    print("Checking Hyper-V installation...")

    ps = """
$feature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
if ($feature.State -ne "Enabled") {
    Write-Error "Hyper-V is not enabled on this system."
}
"""
    run_ps(ps)


def verify_iso_files():
    print("Verifying ISO installation media...")

    if not os.path.exists(SERVER_ISO):
        raise FileNotFoundError(f"Server ISO not found: {SERVER_ISO}")

    if not os.path.exists(WIN11_ISO):
        raise FileNotFoundError(f"Windows 11 ISO not found: {WIN11_ISO}")


def create_lab_directory():
    print("Creating lab directory...")
    os.makedirs(LAB_ROOT, exist_ok=True)


def create_unattend_directory():
    print("Creating unattended install directory")
    os.makedirs(UNATTEND_DIR, exist_ok=True)


# ------------------------------------------------
# XML Unattended Install Generation
# ------------------------------------------------

def generate_router_unattend():
    xml = f"""<unattend xmlns="urn:schemas-microsoft-com:unattend">

  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup">

      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/INDEX</Key>
              <Value>1</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>1</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>

      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add">
              <Order>1</Order>
              <Type>Primary</Type>
              <Size>100</Size>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>2</Order>
              <Type>Primary</Type>
              <Extend>true</Extend>
            </CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add">
              <Order>1</Order>
              <PartitionID>1</PartitionID>
              <Format>NTFS</Format>
              <Label>System</Label>
            </ModifyPartition>
            <ModifyPartition wcm:action="add">
              <Order>2</Order>
              <PartitionID>2</PartitionID>
              <Format>NTFS</Format>
              <Label>Windows</Label>
              <Letter>C</Letter>
            </ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>

      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>

    </component>
  </settings>

  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup">

      <ComputerName>ACME-Router</ComputerName>

      <AutoLogon>
        <Username>Administrator</Username>
        <Enabled>true</Enabled>
        <Password>
          <Value>Password123!</Value>
          <PlainText>true</PlainText>
        </Password>
      </AutoLogon>

      <UserAccounts>
        <AdministratorPassword>
          <Value>Password123!</Value>
          <PlainText>true</PlainText>
        </AdministratorPassword>
      </UserAccounts>

      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <NetworkLocation>Work</NetworkLocation>
        <ProtectYourPC>1</ProtectYourPC>
      </OOBE>

    </component>
  </settings>

</unattend>
"""
    with open(ROUTER_UNATTEND, "w", encoding="utf-8") as f:
        f.write(xml)


def generate_domain_controller_unattend():
    xml = f"""<unattend xmlns="urn:schemas-microsoft-com:unattend">

  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup">

      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/INDEX</Key>
              <Value>1</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>1</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>

      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add">
              <Order>1</Order>
              <Type>Primary</Type>
              <Size>100</Size>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>2</Order>
              <Type>Primary</Type>
              <Extend>true</Extend>
            </CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add">
              <Order>1</Order>
              <PartitionID>1</PartitionID>
              <Format>NTFS</Format>
              <Label>System</Label>
            </ModifyPartition>
            <ModifyPartition wcm:action="add">
              <Order>2</Order>
              <PartitionID>2</PartitionID>
              <Format>NTFS</Format>
              <Label>Windows</Label>
              <Letter>C</Letter>
            </ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>

      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>

    </component>
  </settings>

  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup">

      <ComputerName>ACME-DC01</ComputerName>

      <AutoLogon>
        <Username>Administrator</Username>
        <Enabled>true</Enabled>
        <Password>
          <Value>Password123!</Value>
          <PlainText>true</PlainText>
        </Password>
      </AutoLogon>

      <UserAccounts>
        <AdministratorPassword>
          <Value>Password123!</Value>
          <PlainText>true</PlainText>
        </AdministratorPassword>
      </UserAccounts>

      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <NetworkLocation>Work</NetworkLocation>
        <ProtectYourPC>1</ProtectYourPC>
      </OOBE>

    </component>
  </settings>

</unattend>
"""
    with open(DC_UNATTEND, "w", encoding="utf-8") as f:
        f.write(xml)


def generate_workstation_unattend():
    xml = f"""<unattend xmlns="urn:schemas-microsoft-com:unattend">

  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup">

      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/INDEX</Key>
              <Value>1</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>1</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>

      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add">
              <Order>1</Order>
              <Type>Primary</Type>
              <Size>100</Size>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>2</Order>
              <Type>Primary</Type>
              <Extend>true</Extend>
            </CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add">
              <Order>1</Order>
              <PartitionID>1</PartitionID>
              <Format>NTFS</Format>
              <Label>System</Label>
            </ModifyPartition>
            <ModifyPartition wcm:action="add">
              <Order>2</Order>
              <PartitionID>2</PartitionID>
              <Format>NTFS</Format>
              <Label>Windows</Label>
              <Letter>C</Letter>
            </ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>

      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>

    </component>
  </settings>

  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup">

      <ComputerName>ACME-WKS01</ComputerName>

      <AutoLogon>
        <Username>Administrator</Username>
        <Enabled>true</Enabled>
        <Password>
          <Value>Password123!</Value>
          <PlainText>true</PlainText>
        </Password>
      </AutoLogon>

      <UserAccounts>
        <AdministratorPassword>
          <Value>Password123!</Value>
          <PlainText>true</PlainText>
        </AdministratorPassword>
      </UserAccounts>

      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <NetworkLocation>Work</NetworkLocation>
        <ProtectYourPC>1</ProtectYourPC>
      </OOBE>

    </component>
  </settings>

</unattend>
"""
    with open(WORKSTATION_UNATTEND, "w", encoding="utf-8") as f:
        f.write(xml)


def generate_unattend_files():
    create_unattend_directory()
    print("Generating unattended install files")
    generate_router_unattend()
    generate_domain_controller_unattend()
    generate_workstation_unattend()


# ------------------------------------------------
# Virtual Switch
# ------------------------------------------------

def create_external_switch():
    print("Creating external internet switch")

    ps = """
$adapter = Get-NetAdapter |
Where-Object {
    $_.Status -eq "Up" -and
    $_.InterfaceDescription -notmatch "Virtual|VMware|Hyper-V|VirtualBox|VPN|AnyConnect"
} |
Select-Object -First 1
if (-not $adapter) {
    throw "No valid physical network adapter found for external switch."
}
"""
    run_ps(ps)


def configure_router_network():
    print("Adding second network adapter to router")

    ps = """
$vm = "ACME-Router"
$external = "ACME-External"

Add-VMNetworkAdapter `
    -VMName $vm `
    -SwitchName $external `
    -Name "ExternalAdapter"
"""
    run_ps(ps)


# ------------------------------------------------
# Base VM Creation
# ------------------------------------------------

def create_vm(name, memory_mb, vhd_size_gb, iso_path):
    vm_path = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")
    os.makedirs(vm_path, exist_ok=True)

    if is_windows_installed(name):
        print(f"[INFO] Windows is already installed on {name}, skipping VM creation.")
        return

    print(f"Creating VM {name}")

    # Determine the correct unattend XML filename for this VM
    unattend_xml_name = f"{name.lower()}_autounattend.xml"

    ps = f"""
$vmName = "{name}"
$vmPath = "{vm_path}"
$vhdPath = "{vhd_path}"

if (-not (Get-VM -Name $vmName -ErrorAction SilentlyContinue)) {{

    New-VHD `
        -Path $vhdPath `
        -SizeBytes {vhd_size_gb}GB `
        -Dynamic

    New-VM `
        -Name $vmName `
        -MemoryStartupBytes {memory_mb}MB `
        -Generation 2 `
        -VHDPath $vhdPath `
        -Path $vmPath `
        -SwitchName "{SWITCH_NAME}"

    Set-VMDvdDrive `
        -VMName $vmName `
        -Path "{iso_path}"

    Set-VMFirmware `
        -VMName $vmName `
        -FirstBootDevice (Get-VMDvdDrive -VMName $vmName)

    # Create ISO with unattend file using IMAPI COM object
    $unattendPath = "{UNATTEND_DIR}\\{unattend_xml_name}"

    if (Test-Path $unattendPath) {{
        $isoPath = "$vmPath\\autounattend.iso"

        $fsi = New-Object -ComObject IMAPI2FS.MsftFileSystemImage
        $fsi.FileSystemsToCreate = 1
        $fsi.Root.AddFile("autounattend.xml", $unattendPath)

        $result = $fsi.CreateResultImage()
        $stream = $result.ImageStream

        $file = [System.IO.File]::Create($isoPath)
        $buffer = New-Object byte[] 2048

        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {{
            $file.Write($buffer, 0, $read)
        }}

        $file.Close()

        Add-VMDvdDrive -VMName $vmName -Path $isoPath
    }}
}}
"""
    run_ps(ps)


# ------------------------------------------------
# Specific VM Builders
# ------------------------------------------------

def create_router_vm():
    print("Creating router VM")
    create_vm(ROUTER_VM, memory_mb=2048, vhd_size_gb=40, iso_path=SERVER_ISO)


def create_domain_controller_vm():
    print("Creating domain controller VM")
    create_vm(DC_VM, memory_mb=4096, vhd_size_gb=60, iso_path=SERVER_ISO)


def create_workstation_vm():
    print("Creating workstation VM")
    create_vm(WORKSTATION_VM, memory_mb=4096, vhd_size_gb=60, iso_path=WIN11_ISO)


# ------------------------------------------------
# Installation Detection
# ------------------------------------------------

def is_windows_installed(vm_name):
    ps = f"""
$vm = Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue
if ($vm -eq $null) {{ Write-Output "False"; exit }}

$vhd = (Get-VMHardDiskDrive -VMName "{vm_name}").Path

$mounted = Mount-VHD -Path $vhd -Passthru -ErrorAction SilentlyContinue

$drive = ($mounted | Get-Disk | Get-Partition | Get-Volume |
Where-Object {{$_.FileSystemLabel -eq "Windows"}}).DriveLetter

if ($drive -and (Test-Path "$($drive):\\Windows\\System32")) {{
    Write-Output "True"
}} else {{
    Write-Output "False"
}}

Dismount-VHD -Path $vhd -ErrorAction SilentlyContinue
"""
    result = run_ps(ps, return_output=True)

    if not result:
        return False

    return result.strip().lower() == "true"


import time


def wait_for_vm_install(vm_name, timeout_minutes=60, poll_interval=20):
    print(f"[WAIT] Waiting for Windows installation on {vm_name}...")

    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    last_state = None

    while True:
        elapsed = time.time() - start_time

        if elapsed > timeout_seconds:
            raise TimeoutError(
                f"[FAIL] Timeout waiting for {vm_name} to finish installing Windows."
            )

        try:
            installed = is_windows_installed(vm_name)
        except Exception as e:
            print(f"[WARN] Detection error for {vm_name}: {e}")
            installed = False

        if installed != last_state:
            state_str = "INSTALLED ✅" if installed else "INSTALLING ⏳"
            print(f"[STATUS] {vm_name}: {state_str}")
            last_state = installed

        if installed:
            print(f"[DONE] {vm_name} installation detected.")
            return True

        time.sleep(poll_interval)


# ------------------------------------------------
# Start VMs
# ------------------------------------------------

def wait_for_all_installs():
    wait_for_vm_install(ROUTER_VM)
    wait_for_vm_install(DC_VM)
    wait_for_vm_install(WORKSTATION_VM)


def start_vm(vm_name):
    print(f"Starting VM {vm_name}")
    ps = f'Start-VM -Name "{vm_name}"'
    run_ps(ps)


def start_router():
    print("Starting router VM")
    run_ps('Start-VM -Name "ACME-Router"')


def start_all_vms():
    start_router()
    start_vm(DC_VM)
    start_vm(WORKSTATION_VM)


# ------------------------------------------------
# PowerShell Direct (Run Commands Inside VM)
# ------------------------------------------------

def run_command_in_vm(vm_name, command, retries=10, delay=15):
    print(f"[VM EXEC] {vm_name}")

    ps = f"""
$secpasswd = ConvertTo-SecureString "Password123!" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $secpasswd)

Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{command}
}}
"""
    for attempt in range(retries):
        try:
            run_ps(ps)
            return
        except Exception as e:
            print(f"[RETRY] {vm_name} not ready yet ({attempt+1}/{retries})")
            time.sleep(delay)

    raise Exception(f"[FAIL] Could not execute command in {vm_name}")


# ------------------------------------------------
# Active Directory Installation
# ------------------------------------------------

def install_active_directory():
    print("[STEP] Installing Active Directory on DC")

    command = """
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools

Import-Module ADDSDeployment

Install-ADDSForest `
    -DomainName "ad.acme.edu" `
    -SafeModeAdministratorPassword (ConvertTo-SecureString "Password123!" -AsPlainText -Force) `
    -Force:$true
"""
    run_command_in_vm(DC_VM, command)


# ------------------------------------------------
# DHCP Configuration
# ------------------------------------------------

def configure_dhcp():
    print("[STEP] Configuring DHCP")

    command = """
Install-WindowsFeature DHCP -IncludeManagementTools

Add-DhcpServerv4Scope `
    -Name "ACME Scope" `
    -StartRange 192.168.4.100 `
    -EndRange 192.168.4.200 `
    -SubnetMask 255.255.255.0

Set-DhcpServerv4OptionValue `
    -Router 192.168.4.1 `
    -DnsServer 192.168.4.3 `
    -DnsDomain "ad.acme.edu"
"""
    run_command_in_vm(DC_VM, command)


# ------------------------------------------------
# Active Directory Structure
# ------------------------------------------------

def configure_active_directory_structure():
    print("[STEP] Creating AD structure")

    command = """
Import-Module ActiveDirectory

New-ADOrganizationalUnit -Name "CorporateOffice" -Path "DC=ad,DC=acme,DC=edu"
New-ADOrganizationalUnit -Name "Users" -Path "OU=CorporateOffice,DC=ad,DC=acme,DC=edu"
New-ADOrganizationalUnit -Name "Computers" -Path "OU=CorporateOffice,DC=ad,DC=acme,DC=edu"

New-ADUser `
    -Name "SecTest" `
    -SamAccountName "SecTest" `
    -AccountPassword (ConvertTo-SecureString "Password123!" -AsPlainText -Force) `
    -Enabled $true `
    -Path "OU=Users,OU=CorporateOffice,DC=ad,DC=acme,DC=edu"
"""
    run_command_in_vm(DC_VM, command)


# ------------------------------------------------
# File Shares
# ------------------------------------------------

def configure_file_shares():
    print("[STEP] Creating shared folders")

    command = """
New-Item -Path "C:\\Shares" -ItemType Directory -Force
New-Item -Path "C:\\Shares\\Users$" -ItemType Directory -Force

New-SmbShare -Name "Users$" -Path "C:\\Shares\\Users$" -FullAccess "Everyone"
"""
    run_command_in_vm(DC_VM, command)


# ------------------------------------------------
# Join Workstation to Domain
# ------------------------------------------------

def join_workstation_to_domain():
    print("[STEP] Joining workstation to domain")

    command = """
$secpasswd = ConvertTo-SecureString "Password123!" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("ad\\Administrator", $secpasswd)

Add-Computer -DomainName "ad.acme.edu" -Credential $cred -Force -Restart
"""
    run_command_in_vm(WORKSTATION_VM, command)
    wait_for_vm_install(WORKSTATION_VM)


# ------------------------------------------------
# FULL POST-INSTALL PIPELINE
# ------------------------------------------------

def verify_environment():
    print("[VERIFY] Running full validation...")

    checks = [
        ("Domain Exists", "Get-ADDomain"),
        ("DHCP Scope", "Get-DhcpServerv4Scope"),
        ("Users", "Get-ADUser -Filter *"),
        ("Shares", "Get-SmbShare"),
    ]

    for name, cmd in checks:
        try:
            run_command_in_vm(DC_VM, cmd)
            print(f"[PASS] {name}")
        except Exception:
            raise Exception(f"[FAIL] {name}")


def configure_full_environment():
    run_step("ad_install", install_active_directory)
    run_step("wait_dc", lambda: wait_for_vm_install(DC_VM))
    run_step("dhcp", configure_dhcp)
    run_step("ad_structure", configure_active_directory_structure)
    run_step("shares", configure_file_shares)
    run_step("join_domain", join_workstation_to_domain)
    run_step("verify", verify_environment)

    print("[SUCCESS] Full domain environment configured.")