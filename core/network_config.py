from utils.powershell_runner import run_ps
from config_loader import get_network_config, get_router_name, get_dc_name, get_admin_password

ROUTER_VM  = get_router_name()   # AcmeRtr01
DC_VM      = get_dc_name()       # AcmePDC01
ADMIN_PASS = get_admin_password()


def _run_on_vm(vm_name, ps_script):
    wrapped = f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


def configure_router():
    print("\n[NET] Configuring router (NAT + Routing)...\n")
    net     = get_network_config()
    gateway = net.get("gateway", "192.168.4.1")
    subnet  = net.get("subnet",  "192.168.4.0/24")
    ps = f"""
Install-WindowsFeature RemoteAccess -IncludeManagementTools
Install-WindowsFeature Routing
Import-Module RemoteAccess
$internal = Get-NetAdapter | Where-Object {{$_.Name -notlike "*External*" -and $_.Status -eq "Up"}} | Select-Object -First 1
$external = Get-NetAdapter | Where-Object {{$_.Name -like "*External*"}} | Select-Object -First 1
New-NetIPAddress -InterfaceIndex $internal.ifIndex -IPAddress "{gateway}" -PrefixLength 24 -ErrorAction SilentlyContinue
if (-not (Get-NetNat -ErrorAction SilentlyContinue)) {{
    New-NetNat -Name "ACMENAT" -InternalIPInterfaceAddressPrefix "{subnet}"
}}
Set-Service RemoteAccess -StartupType Automatic
Start-Service RemoteAccess
"""
    _run_on_vm(ROUTER_VM, ps)
    print("[NET] Router configured.\n")


def configure_domain_controller_network():
    print("[NET] Configuring DC network...")
    net     = get_network_config()
    ip      = net.get("dns_primary", "192.168.4.3")
    gateway = net.get("gateway",    "192.168.4.1")
    ps = f"""
$a = Get-NetAdapter | Where-Object {{$_.Status -eq "Up"}} | Select-Object -First 1
New-NetIPAddress -InterfaceIndex $a.ifIndex -IPAddress "{ip}" -PrefixLength 24 `
    -DefaultGateway "{gateway}" -ErrorAction SilentlyContinue
Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ServerAddresses ("{ip}")
"""
    _run_on_vm(DC_VM, ps)
    print("[NET] DC network configured.\n")


def configure_workstation_network(vm_name):
    print(f"[NET] Setting {vm_name} to DHCP...")
    ps = """
$a = Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | Select-Object -First 1
Set-NetIPInterface -InterfaceIndex $a.ifIndex -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ResetServerAddresses
"""
    _run_on_vm(vm_name, ps)
    print(f"[NET] {vm_name} set to DHCP.\n")


def configure_networking(workstations):
    print("\n========== NETWORK CONFIGURATION ==========\n")
    configure_router()
    configure_domain_controller_network()
    for ws in workstations:
        configure_workstation_network(ws)
    print("\n[NET] Network configuration complete.\n")