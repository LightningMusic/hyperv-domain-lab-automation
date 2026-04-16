import os
import time
from typing import Callable, Optional

from utils.powershell_runner import run_ps
from config_loader import load_config


# ------------------------------------------------
# Paths / Config
# ------------------------------------------------

CONFIG = load_config()

LAB_ROOT = CONFIG["paths"]["lab_root"]
UNATTEND_DIR = CONFIG["paths"]["unattend_dir"]

SERVER_ISO = CONFIG["install_media"]["server_iso"]
WIN11_ISO = CONFIG["install_media"]["windows_iso"]

CHECKPOINT_FILE = os.path.join(LAB_ROOT, "deployment_state.txt")


# ------------------------------------------------
# Checkpoints
# ------------------------------------------------

def load_checkpoint() -> Optional[str]:
    if not os.path.exists(CHECKPOINT_FILE):
        return None
    return open(CHECKPOINT_FILE).read().strip()


def save_checkpoint(step: str):
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(step)


def run_step(step: str, func: Callable):
    current = load_checkpoint()

    if current == step:
        print(f"[SKIP] {step}")
        return

    print(f"[RUN] {step}")
    func()
    save_checkpoint(step)


# ------------------------------------------------
# Config Helpers
# ------------------------------------------------

def get_vm(role: str) -> dict:
    for vm in CONFIG["virtual_machines"]:
        if vm["role"] == role:
            return vm
    raise ValueError(f"VM role not found: {role}")


def get_vm_name(role: str) -> str:
    return get_vm(role)["name"]


def get_iso(role: str) -> str:
    return SERVER_ISO if role in ("router", "domain_controller") else WIN11_ISO


def get_switch() -> str:
    return CONFIG["hyperv"]["switches"][0]["name"]


def get_domain() -> str:
    return CONFIG["environment"]["domain_name"]


def get_admin_password() -> str:
    return CONFIG["environment"]["admin_password"]


# ------------------------------------------------
# Validation
# ------------------------------------------------

def verify_environment():
    print("[VERIFY] Checking Hyper-V + ISOs")

    run_ps("""
$feature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
if ($feature.State -ne "Enabled") {
    throw "Hyper-V is not enabled."
}
""")

    for iso in (SERVER_ISO, WIN11_ISO):
        if not os.path.exists(iso):
            raise FileNotFoundError(iso)


# ------------------------------------------------
# VM Creation
# ------------------------------------------------

def create_vm(vm: dict):
    name = vm["name"]
    memory = vm["ram_gb"] * 1024
    disk = vm["disk_gb"]
    switch = get_switch()

    vm_path = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")

    os.makedirs(vm_path, exist_ok=True)

    print(f"[VM] Creating {name}")

    ps = f"""
if (-not (Get-VM -Name "{name}" -ErrorAction SilentlyContinue)) {{

    New-VHD -Path "{vhd_path}" -SizeBytes {disk}GB -Dynamic

    New-VM `
        -Name "{name}" `
        -MemoryStartupBytes {memory}MB `
        -Generation 2 `
        -VHDPath "{vhd_path}" `
        -Path "{vm_path}" `
        -SwitchName "{switch}"

    Set-VMDvdDrive -VMName "{name}" -Path "{get_iso(vm['role'])}"
}}
"""
    run_ps(ps)


def start_vm(name: str):
    run_ps(f'Start-VM -Name "{name}"')


# ------------------------------------------------
# Install Detection
# ------------------------------------------------

def is_windows_installed(vm_name: str) -> bool:
    result = run_ps(f"""
$vm = Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue
if (-not $vm) {{ "False"; exit }}

$vhd = (Get-VMHardDiskDrive -VMName "{vm_name}").Path
$disk = Mount-VHD -Path $vhd -Passthru

$vol = ($disk | Get-Disk | Get-Partition | Get-Volume |
Where-Object {{$_.FileSystemLabel -eq "Windows"}})

if ($vol) {{ "True" }} else {{ "False" }}

Dismount-VHD -Path $vhd
""", return_output=True)

    return str(result).strip().lower() == "true"


def wait_for_install(vm_name: str, timeout=3600):
    print(f"[WAIT] {vm_name}")

    start = time.time()

    while time.time() - start < timeout:
        if is_windows_installed(vm_name):
            print(f"[DONE] {vm_name}")
            return
        time.sleep(20)

    raise TimeoutError(vm_name)


# ------------------------------------------------
# PowerShell Direct
# ------------------------------------------------

def run_in_vm(vm: str, command: str):
    pw = get_admin_password()

    ps = f"""
$sec = ConvertTo-SecureString "{pw}" -AsPlainText -Force
$cred = New-Object PSCredential ("Administrator", $sec)

Invoke-Command -VMName "{vm}" -Credential $cred -ScriptBlock {{
{command}
}}
"""
    run_ps(ps)


# ------------------------------------------------
# AD + Services
# ------------------------------------------------

def install_active_directory():
    vm = get_vm_name("domain_controller")

    run_in_vm(vm, f"""
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools

Install-ADDSForest `
    -DomainName "{get_domain()}" `
    -SafeModeAdministratorPassword (ConvertTo-SecureString "{get_admin_password()}" -AsPlainText -Force) `
    -Force:$true
""")


def configure_dhcp():
    vm = get_vm_name("domain_controller")

    run_in_vm(vm, f"""
Install-WindowsFeature DHCP -IncludeManagementTools

Add-DhcpServerv4Scope `
    -Name "ACME Scope" `
    -StartRange 192.168.4.100 `
    -EndRange 192.168.4.200 `
    -SubnetMask 255.255.255.0

Set-DhcpServerv4OptionValue `
    -Router 192.168.4.1 `
    -DnsServer 192.168.4.3 `
    -DnsDomain "{get_domain()}"
""")


def join_domain():
    vm = get_vm_name("workstation")

    run_in_vm(vm, f"""
$sec = ConvertTo-SecureString "{get_admin_password()}" -AsPlainText -Force
$cred = New-Object PSCredential ("{get_domain()}\\Administrator", $sec)

Add-Computer -DomainName "{get_domain()}" -Credential $cred -Force -Restart
""")