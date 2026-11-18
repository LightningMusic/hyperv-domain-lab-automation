"""
core/network_config.py - guest networking, all over PowerShell Direct.

Topology (nothing here touches the host's network):

    host ── Default Switch ── [Uplink]  AcmeRtr01  [Lab] ── AcmeBusiness (PRIVATE) ── DC, workstations
                              (DHCP, NAT'd by the host)   (192.168.4.1/24, RRAS NAT)

NICs are identified by the name Hyper-V gave them ("Lab" / "Uplink"); the guest
renames its adapters to match using Hyper-V consistent device naming.
"""
from config_loader import get_network_config, get_router_name, get_dc_name
from core.hyperv_manager import run_in_vm
from utils.logger import get_logger

log = get_logger("network_config")

ROUTER_VM = get_router_name()   # AcmeRtr01
DC_VM     = get_dc_name()       # AcmePDC01

# Rename guest adapters to the NIC names set in Hyper-V ("Lab", "Uplink").
_RENAME_NICS = r"""
Get-NetAdapterAdvancedProperty -RegistryKeyword HyperVNetworkAdapterName -ErrorAction SilentlyContinue |
    ForEach-Object { if ($_.Name -ne $_.DisplayValue) { Rename-NetAdapter -Name $_.Name -NewName $_.DisplayValue } }
if (-not (Get-NetAdapter -Name 'Lab' -ErrorAction SilentlyContinue)) { throw "Guest NIC 'Lab' not found" }
"""

_ROUTER = _RENAME_NICS + r"""
if (-not (Get-NetAdapter -Name 'Uplink' -ErrorAction SilentlyContinue)) { throw "Guest NIC 'Uplink' not found" }

# Lab side: the lab's default gateway
if (-not (Get-NetIPAddress -InterfaceAlias 'Lab' -IPAddress '__GATEWAY__' -ErrorAction SilentlyContinue)) {
    Get-NetIPAddress -InterfaceAlias 'Lab' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
    New-NetIPAddress -InterfaceAlias 'Lab' -IPAddress '__GATEWAY__' -PrefixLength __PREFIX__ | Out-Null
}

# Uplink side: DHCP from Hyper-V's Default Switch (the host NATs it, we change nothing on the host)
Set-NetIPInterface -InterfaceAlias 'Uplink' -Dhcp Enabled
Set-NetIPInterface -InterfaceAlias 'Lab', 'Uplink' -Forwarding Enabled

# Routing + NAT (RRAS)
if (-not (Get-WindowsFeature Routing).Installed) { Install-WindowsFeature Routing -IncludeManagementTools | Out-Null }
try { Install-RemoteAccess -VpnType RoutingOnly -ErrorAction Stop | Out-Null } catch { Write-Output "RemoteAccess: $($_.Exception.Message)" }
Set-Service RemoteAccess -StartupType Automatic
if ((Get-Service RemoteAccess).Status -ne 'Running') { Start-Service RemoteAccess }

$nat = (netsh routing ip nat show interface 2>&1 | Out-String)
if ($nat -notmatch 'Uplink') {
    netsh routing ip nat install | Out-Null
    netsh routing ip nat add interface "Uplink" | Out-Null
    netsh routing ip nat set interface "Uplink" mode=full | Out-Null
    netsh routing ip nat add interface "Lab" mode=private | Out-Null
}
$nat = (netsh routing ip nat show interface 2>&1 | Out-String)
if ($nat -notmatch 'Uplink') { throw "RRAS NAT was not configured: $nat" }

# The router itself must reach the internet through the uplink
$ok = $false
for ($i = 0; $i -lt 12 -and -not $ok; $i++) {
    $ok = [bool](Test-Connection 1.1.1.1 -Count 1 -Quiet -ErrorAction SilentlyContinue)
    if (-not $ok) { Start-Sleep -Seconds 5 }
}
if (-not $ok) { throw "Router uplink has no internet (Default Switch NAT unreachable)" }
Write-Output "Router OK: NAT configured, uplink online"
"""

_DC = _RENAME_NICS + r"""
if (-not (Get-NetIPAddress -InterfaceAlias 'Lab' -IPAddress '__IP__' -ErrorAction SilentlyContinue)) {
    Get-NetIPAddress -InterfaceAlias 'Lab' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
    Remove-NetRoute -InterfaceAlias 'Lab' -DestinationPrefix '0.0.0.0/0' -Confirm:$false -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceAlias 'Lab' -IPAddress '__IP__' -PrefixLength __PREFIX__ -DefaultGateway '__GATEWAY__' | Out-Null
}
Set-DnsClientServerAddress -InterfaceAlias 'Lab' -ServerAddresses '__IP__'
Write-Output "DC network OK: __IP__"
"""

_CLIENT = _RENAME_NICS + r"""
Set-NetIPInterface -InterfaceAlias 'Lab' -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceAlias 'Lab' -ResetServerAddresses
Write-Output "DHCP client OK"
"""

_RENEW = r"""
ipconfig /renew | Out-Null
$a = Get-NetIPAddress -InterfaceAlias 'Lab' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '169.254*' }
if (-not $a) { throw "No DHCP lease yet on 'Lab'" }
Write-Output "Lease: $($a.IPAddress)"
"""


def _prefix_len(subnet: str) -> str:
    return subnet.split("/")[1] if "/" in subnet else "24"


def _fill(script: str, **kw) -> str:
    for k, v in kw.items():
        script = script.replace(f"__{k.upper()}__", str(v))
    return script


def configure_router():
    log.info("[NET] Configuring router (Lab 192.168.4.1 + RRAS NAT to the Default Switch uplink)")
    net = get_network_config()
    run_in_vm(ROUTER_VM, _fill(_ROUTER, gateway=net.get("gateway", "192.168.4.1"),
                               prefix=_prefix_len(net.get("subnet", "192.168.4.0/24"))))
    log.info("[NET] Router configured.")


def configure_domain_controller_network():
    log.info("[NET] Configuring DC network")
    net = get_network_config()
    run_in_vm(DC_VM, _fill(_DC, ip=net.get("dns_primary", "192.168.4.3"),
                           gateway=net.get("gateway", "192.168.4.1"),
                           prefix=_prefix_len(net.get("subnet", "192.168.4.0/24"))))
    log.info("[NET] DC network configured.")


def configure_workstation_network(vm_name):
    log.info(f"[NET] Setting {vm_name} to DHCP")
    run_in_vm(vm_name, _CLIENT)
    log.info(f"[NET] {vm_name} set to DHCP.")


def renew_dhcp(vm_name):
    """Ask for a lease now (call once the DHCP server on the DC is up)."""
    run_in_vm(vm_name, _RENEW, retries=6, delay=15)


def configure_networking(workstations):
    log.info("========== NETWORK CONFIGURATION ==========")
    configure_router()
    configure_domain_controller_network()
    for ws in workstations:
        configure_workstation_network(ws)
    log.info("[NET] Network configuration complete.")
