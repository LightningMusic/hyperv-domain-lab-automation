from utils.powershell_runner import run_ps
from config_loader import get_domain_config, get_dc_name, get_admin_password
from utils.logger import get_logger

log = get_logger("dns_manager")
DC_VM      = get_dc_name()
ADMIN_PASS = get_admin_password()


def _run_on_dc(ps):
    wrapped = f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{
{ps}
}}
"""
    return run_ps(wrapped, return_output=True)


def install_dns_role():
    log.info("[DNS] Ensuring DNS role installed...")
    _run_on_dc("""
$f = Get-WindowsFeature DNS
if (-not $f.Installed) { Install-WindowsFeature DNS -IncludeManagementTools; Write-Output "DNS installed" }
else { Write-Output "DNS already installed" }
""")


def zone_exists(zone_name):
    r = _run_on_dc(f"""
$z = Get-DnsServerZone -Name "{zone_name}" -ErrorAction SilentlyContinue
if ($z) {{ "True" }} else {{ "False" }}
""")
    return bool(r) and r.strip().lower() == "true"


def create_primary_zone(zone_name):
    if zone_exists(zone_name):
        log.info(f"[DNS] Zone exists: {zone_name}"); return
    _run_on_dc(f"""
Import-Module DnsServer
Add-DnsServerPrimaryZone -Name "{zone_name}" -ReplicationScope "Forest" -DynamicUpdate "Secure"
""")


def configure_forwarders(ips=None):
    if not ips: ips = ["1.1.1.1", "8.8.8.8"]
    ip_list = ", ".join(f'"{ip}"' for ip in ips)
    log.info(f"[DNS] Forwarders: {ips}")
    _run_on_dc(f"Set-DnsServerForwarder -IPAddress {ip_list} -PassThru")


def configure_scavenging(zone_name):
    _run_on_dc(f"""
Set-DnsServerScavenging -ScavengingState $true -ScavengingInterval 7.00:00:00 -ApplyOnAllZones
Set-DnsServerZoneAging -Name "{zone_name}" -Aging $true `
    -NoRefreshInterval 168:00:00 -RefreshInterval 168:00:00
""")


def test_resolution(hostname):
    r = _run_on_dc(f'Resolve-DnsName "{hostname}" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress')
    log.info(f"[DNS] {hostname} → {(r or 'UNRESOLVED').strip()}")


def flush_dns_cache():
    _run_on_dc("Clear-DnsServerCache -Force")


def configure_dns():
    domain = get_domain_config()["name"]
    log.info(f"\n[DNS] Configuring DNS server for {domain}\n")
    install_dns_role()
    if not zone_exists(domain):
        create_primary_zone(domain)
    configure_forwarders(["1.1.1.1", "8.8.8.8"])
    configure_scavenging(domain)
    test_resolution(f"AcmePDC01.{domain}")
    test_resolution("google.com")
    log.info("\n[DNS] DNS configuration COMPLETE.\n")