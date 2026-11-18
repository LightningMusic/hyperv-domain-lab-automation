"""
core/network_config.py - guest networking, all over PowerShell Direct.

Topology (nothing here touches the host's network):

    host ── Default Switch ── [Uplink]  AcmeRtr01  [Lab] ── AcmeBusiness (PRIVATE) ── DC, workstations
                              (DHCP, NAT'd by the host)   (192.168.4.1/24, RRAS NAT)

NICs are identified by the name Hyper-V gave them ("Lab" / "Uplink"); the guest
renames its adapters to match using Hyper-V consistent device naming.
"""
from config_loader import get_network_config, get_router_name, get_dc_name
from core.hyperv_manager import run_in_vm, run_in_vm_output, reboot_vm
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

# Stage 1 (before the reboot): NICs, addresses, and the Routing role.  The role is not
# usable until the guest has restarted ("InstallPending"), so this stage reports whether
# a reboot is needed instead of trying to use it.
_ROUTER_PREP = _RENAME_NICS + r"""
if (-not (Get-NetAdapter -Name 'Uplink' -ErrorAction SilentlyContinue)) { throw "Guest NIC 'Uplink' not found" }

# Lab side: the lab's default gateway
if (-not (Get-NetIPAddress -InterfaceAlias 'Lab' -IPAddress '__GATEWAY__' -ErrorAction SilentlyContinue)) {
    Get-NetIPAddress -InterfaceAlias 'Lab' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
    New-NetIPAddress -InterfaceAlias 'Lab' -IPAddress '__GATEWAY__' -PrefixLength __PREFIX__ | Out-Null
}

# Uplink side: DHCP from Hyper-V's Default Switch (the host NATs it, we change nothing on the host)
Set-NetIPInterface -InterfaceAlias 'Uplink' -Dhcp Enabled
Set-NetIPInterface -InterfaceAlias 'Lab', 'Uplink' -Forwarding Enabled

$restart = $false
if (-not (Get-WindowsFeature Routing).Installed) {
    $r = Install-WindowsFeature Routing -IncludeManagementTools
    if (-not $r.Success) { throw "Installing the Routing role failed: $($r.ExitCode)" }
    if ("$($r.RestartNeeded)" -ne 'No') { $restart = $true }
}
if ((Get-WindowsFeature Routing, RemoteAccess).InstallState -contains 'InstallPending') { $restart = $true }
if ($restart) { Write-Output "NEEDS_REBOOT" } else { Write-Output "NO_REBOOT_NEEDED" }
"""

# Stage 2 (after the reboot): RRAS routing + NAT, then prove the uplink works.
_ROUTER_NAT = r"""
if (-not (Get-Command Install-RemoteAccess -ErrorAction SilentlyContinue)) { throw "Routing role is not active (reboot did not complete it)" }
try { Install-RemoteAccess -VpnType RoutingOnly -ErrorAction Stop | Out-Null } catch { Write-Output "RemoteAccess: $($_.Exception.Message)" }
Set-Service RemoteAccess -StartupType Automatic
if ((Get-Service RemoteAccess).Status -ne 'Running') { Start-Service RemoteAccess }

# Uplink must hold a real lease (not 169.254.x) before NAT is meaningful
$lease = $false
for ($i = 0; $i -lt 18 -and -not $lease; $i++) {
    $lease = [bool](Get-NetIPAddress -InterfaceAlias 'Uplink' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '169.254*' })
    if (-not $lease) { ipconfig /renew Uplink | Out-Null; Start-Sleep -Seconds 5 }
}
if (-not $lease) { throw "Uplink got no DHCP lease from the Default Switch" }

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
    prep = _fill(_ROUTER_PREP, gateway=net.get("gateway", "192.168.4.1"),
                 prefix=_prefix_len(net.get("subnet", "192.168.4.0/24")))
    out = run_in_vm_output(ROUTER_VM, prep)
    if "NEEDS_REBOOT" in out:
        log.info("[NET] Routing role installed; restarting the router to finish it")
        reboot_vm(ROUTER_VM)
    run_in_vm(ROUTER_VM, _ROUTER_NAT)
    log.info("[NET] Router configured.")


_VERIFY_ROUTER = r"""
$o = [ordered]@{}
$o.Computer   = $env:COMPUTERNAME
$o.Edition    = (Get-ComputerInfo -Property WindowsProductName).WindowsProductName
$o.LabIP      = (Get-NetIPAddress -InterfaceAlias 'Lab' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress -join ','
$o.UplinkIP   = (Get-NetIPAddress -InterfaceAlias 'Uplink' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress -join ','
$o.Forwarding = (Get-NetIPInterface -InterfaceAlias 'Lab','Uplink' -AddressFamily IPv4 | ForEach-Object { "$($_.InterfaceAlias)=$($_.Forwarding)" }) -join ','
$o.RemoteAccess = "$((Get-Service RemoteAccess).Status)/$((Get-Service RemoteAccess).StartType)"
$o.NatInterfaces = ((netsh routing ip nat show interface 2>&1 | Out-String) -split "`r?`n" | Where-Object { $_ -match 'Lab|Uplink' }) -join ' | '
$o.PingInternet = [bool](Test-Connection 1.1.1.1 -Count 2 -Quiet -ErrorAction SilentlyContinue)
$o.ResolveName  = [bool](Resolve-DnsName microsoft.com -Type A -ErrorAction SilentlyContinue)
$o.GetEnumerator() | ForEach-Object { "{0,-14}: {1}" -f $_.Key, $_.Value }
if (-not ($o.PingInternet -and $o.NatInterfaces -match 'Uplink' -and $o.RemoteAccess -like 'Running*')) { throw "Router verification failed" }
"""


def verify_router() -> str:
    """Read back what the router actually ended up with; raises if NAT or the uplink is not working."""
    out = run_in_vm_output(ROUTER_VM, _VERIFY_ROUTER, retries=3, delay=10)
    log.info("[NET] Router state:\n" + out.strip())
    return out


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
