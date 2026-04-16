from utils.powershell_runner import run_ps
from config_loader import get_domain_config, get_network_config
from utils.logger import get_logger

log = get_logger("dns_manager")

DC_VM = "ACME-DC01"


# ------------------------------------------------
# Helper: Run inside DC
# ------------------------------------------------

def run_on_dc(ps_script):
    wrapped = f"""
Invoke-Command -VMName "{DC_VM}" -ScriptBlock {{
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


# ------------------------------------------------
# Install DNS role
# ------------------------------------------------

def install_dns_role():
    log.info("[DNS] Installing DNS Server role...")

    ps = """
$feature = Get-WindowsFeature DNS

if (-not $feature.Installed) {
    Install-WindowsFeature DNS -IncludeManagementTools
    Write-Output "DNS Server role installed."
} else {
    Write-Output "DNS Server role already installed."
}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Check if DNS zone exists
# ------------------------------------------------

def zone_exists(zone_name):
    ps = f"""
$zone = Get-DnsServerZone -Name "{zone_name}" -ErrorAction SilentlyContinue
if ($zone) {{ "True" }} else {{ "False" }}
"""
    result = run_on_dc(ps)
    return result and result.strip().lower() == "true"


# ------------------------------------------------
# Create primary forward lookup zone
# ------------------------------------------------

def create_primary_zone(zone_name):
    log.info(f"[DNS] Creating primary zone: {zone_name}")

    if zone_exists(zone_name):
        log.info(f"[DNS] Zone already exists: {zone_name}")
        return

    ps = f"""
Import-Module DnsServer

Add-DnsServerPrimaryZone `
    -Name "{zone_name}" `
    -ReplicationScope "Forest" `
    -DynamicUpdate "Secure"

Write-Output "Primary zone created: {zone_name}"
"""
    run_on_dc(ps)


# ------------------------------------------------
# Configure DNS forwarders (upstream resolvers)
# ------------------------------------------------

def configure_forwarders(forwarder_ips=None):
    """
    Sets upstream DNS forwarders so lab VMs can resolve external names.
    Defaults to Cloudflare + Google public DNS.
    """

    if forwarder_ips is None:
        forwarder_ips = ["1.1.1.1", "8.8.8.8"]

    log.info(f"[DNS] Configuring forwarders: {forwarder_ips}")

    ip_list = ", ".join([f'"{ip}"' for ip in forwarder_ips])

    ps = f"""
Import-Module DnsServer

Set-DnsServerForwarder -IPAddress {ip_list} -PassThru

Write-Output "DNS forwarders configured: {', '.join(forwarder_ips)}"
"""
    run_on_dc(ps)


# ------------------------------------------------
# Disable DNS root hints (use forwarders only)
# ------------------------------------------------

def disable_root_hints():
    log.info("[DNS] Disabling root hints (forwarder-only mode)...")

    ps = """
Import-Module DnsServer

Set-DnsServerRecursion -Enable $true
Set-DnsServerForwarder -UseRootHint $false

Write-Output "Root hints disabled."
"""
    run_on_dc(ps)


# ------------------------------------------------
# Configure DNS aging and scavenging
# ------------------------------------------------

def configure_scavenging(zone_name, no_refresh_hours=168, refresh_hours=168):
    """
    Enables DNS scavenging to clean up stale records.
    Default: 7-day no-refresh + 7-day refresh window.
    """

    log.info(f"[DNS] Configuring scavenging on zone {zone_name}...")

    ps = f"""
Import-Module DnsServer

# Enable scavenging on the server
Set-DnsServerScavenging `
    -ScavengingState $true `
    -ScavengingInterval 7.00:00:00 `
    -ApplyOnAllZones

# Enable aging on this zone
Set-DnsServerZoneAging `
    -Name "{zone_name}" `
    -Aging $true `
    -NoRefreshInterval {no_refresh_hours}:00:00 `
    -RefreshInterval {refresh_hours}:00:00

Write-Output "Scavenging configured for zone {zone_name}"
"""
    run_on_dc(ps)


# ------------------------------------------------
# Test DNS resolution from inside the DC
# ------------------------------------------------

def test_resolution(hostname):
    log.info(f"[DNS] Testing resolution: {hostname}")

    ps = f"""
$result = Resolve-DnsName "{hostname}" -ErrorAction SilentlyContinue

if ($result) {{
    $result | Select-Object Name, Type, IPAddress | Format-Table
    Write-Output "Resolution OK: {hostname}"
}} else {{
    Write-Output "Resolution FAILED: {hostname}"
}}
"""
    result = run_on_dc(ps)
    if result:
        log.info(result)
    return result


# ------------------------------------------------
# Get DNS server statistics
# ------------------------------------------------

def get_dns_stats():
    log.info("[DNS] Fetching DNS server statistics...")

    ps = """
Import-Module DnsServer

$stats = Get-DnsServerStatistics

Write-Output "Total queries    : $($stats.Query.TotalQueries)"
Write-Output "Successful       : $($stats.Query.SuccessfulResponses)"
Write-Output "Recursive queries: $($stats.Query.RecursiveQueries)"
"""
    result = run_on_dc(ps)
    if result:
        log.info(result)
    return result


# ------------------------------------------------
# Flush DNS cache on DC
# ------------------------------------------------

def flush_dns_cache():
    log.info("[DNS] Flushing DNS server cache...")

    ps = """
Clear-DnsServerCache -Force
Write-Output "DNS cache flushed."
"""
    run_on_dc(ps)


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def configure_dns():
    domain_config = get_domain_config()
    domain_name = domain_config.get("name", "ad.acme.edu")

    log.info("\n[DNS] Starting DNS server configuration...\n")

    # Install DNS role (usually already installed with AD DS)
    install_dns_role()

    # Ensure forward zone exists (AD creates it, but verify)
    if not zone_exists(domain_name):
        create_primary_zone(domain_name)

    # External forwarders so lab can reach the internet
    configure_forwarders(["1.1.1.1", "8.8.8.8"])
    disable_root_hints()

    # Enable scavenging to clean up stale records
    configure_scavenging(domain_name)

    # Test basic resolution
    test_resolution(f"AcmePDC01.{domain_name}")
    test_resolution("google.com")

    log.info("\n[DNS] DNS server configuration COMPLETE.\n")