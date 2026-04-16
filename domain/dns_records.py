from utils.powershell_runner import run_ps
from config_loader import get_domain_config
from utils.logger import get_logger

log = get_logger("dns_records")

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
# Create A Record
# ------------------------------------------------

def create_a_record(name, ip, zone):
    """Creates a DNS A (host) record."""

    log.info(f"[DNS] A record: {name} -> {ip} in zone {zone}")

    ps = f"""
Import-Module DnsServer

if (-not (Get-DnsServerResourceRecord -ZoneName "{zone}" -Name "{name}" `
          -RRType A -ErrorAction SilentlyContinue)) {{

    Add-DnsServerResourceRecordA `
        -ZoneName "{zone}" `
        -Name "{name}" `
        -IPv4Address "{ip}"

    Write-Output "Created A record: {name} -> {ip}"
}} else {{
    Write-Output "A record already exists: {name}"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Create CNAME Record
# ------------------------------------------------

def create_cname_record(alias, target, zone):
    """Creates a DNS CNAME (alias) record."""

    log.info(f"[DNS] CNAME record: {alias} -> {target} in zone {zone}")

    ps = f"""
Import-Module DnsServer

if (-not (Get-DnsServerResourceRecord -ZoneName "{zone}" -Name "{alias}" `
          -RRType CNAME -ErrorAction SilentlyContinue)) {{

    Add-DnsServerResourceRecordCName `
        -ZoneName "{zone}" `
        -Name "{alias}" `
        -HostNameAlias "{target}"

    Write-Output "Created CNAME: {alias} -> {target}"
}} else {{
    Write-Output "CNAME already exists: {alias}"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Create MX Record
# ------------------------------------------------

def create_mx_record(mail_server, zone, preference=10):
    """Creates a DNS MX (mail exchange) record."""

    log.info(f"[DNS] MX record: {mail_server} (pref {preference}) in zone {zone}")

    ps = f"""
Import-Module DnsServer

if (-not (Get-DnsServerResourceRecord -ZoneName "{zone}" -Name "@" `
          -RRType MX -ErrorAction SilentlyContinue)) {{

    Add-DnsServerResourceRecordMX `
        -ZoneName "{zone}" `
        -Name "@" `
        -MailExchange "{mail_server}" `
        -Preference {preference}

    Write-Output "Created MX record: {mail_server}"
}} else {{
    Write-Output "MX record already exists for zone {zone}"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Create Reverse Lookup Zone
# ------------------------------------------------

def create_reverse_lookup_zone(network_id, zone_name=None):
    """
    Creates a reverse lookup zone for PTR records.
    network_id example: "192.168.4"  → zone: "4.168.192.in-addr.arpa"
    """

    if not zone_name:
        octets = network_id.split(".")
        zone_name = ".".join(reversed(octets)) + ".in-addr.arpa"

    log.info(f"[DNS] Creating reverse lookup zone: {zone_name}")

    ps = f"""
Import-Module DnsServer

if (-not (Get-DnsServerZone -Name "{zone_name}" -ErrorAction SilentlyContinue)) {{

    Add-DnsServerPrimaryZone `
        -NetworkID "{network_id}.0/24" `
        -ReplicationScope "Forest"

    Write-Output "Created reverse zone: {zone_name}"
}} else {{
    Write-Output "Reverse zone already exists: {zone_name}"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Create PTR Record
# ------------------------------------------------

def create_ptr_record(ip, fqdn, zone_name):
    """
    Creates a PTR (reverse DNS) record.
    ip example: "192.168.4.45"  → last octet "45" is the record name
    """

    last_octet = ip.split(".")[-1]

    log.info(f"[DNS] PTR record: {last_octet} -> {fqdn} in zone {zone_name}")

    ps = f"""
Import-Module DnsServer

if (-not (Get-DnsServerResourceRecord -ZoneName "{zone_name}" -Name "{last_octet}" `
          -RRType PTR -ErrorAction SilentlyContinue)) {{

    Add-DnsServerResourceRecordPtr `
        -ZoneName "{zone_name}" `
        -Name "{last_octet}" `
        -PtrDomainName "{fqdn}"

    Write-Output "Created PTR: {last_octet} -> {fqdn}"
}} else {{
    Write-Output "PTR record already exists: {last_octet}"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Flush DNS Cache
# ------------------------------------------------

def flush_dns_cache():
    log.info("[DNS] Flushing DNS server cache...")

    ps = """
Clear-DnsServerCache -Force
Write-Output "DNS cache flushed."
"""
    run_on_dc(ps)


# ------------------------------------------------
# Verify DNS record resolves
# ------------------------------------------------

def verify_record(hostname, zone):
    log.info(f"[DNS] Verifying resolution of {hostname}.{zone}...")

    ps = f"""
Resolve-DnsName "{hostname}.{zone}" -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty IPAddress
"""
    result = run_on_dc(ps)

    if result and result.strip():
        log.info(f"[DNS] Resolved {hostname} → {result.strip()}")
        return True
    else:
        log.warning(f"[DNS] Could not resolve {hostname}.{zone}")
        return False


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def configure_dns_records():
    config = get_domain_config()
    domain = config.get("name", "ad.acme.edu")

    log.info("\n[DNS] Starting DNS record configuration...\n")

    # --- Reverse Lookup Zone ---
    create_reverse_lookup_zone("192.168.4")
    reverse_zone = "4.168.192.in-addr.arpa"

    # --- A Records ---
    a_records = [
        ("AcmeRtr01",   "192.168.4.1"),
        ("AcmePDC01",   "192.168.4.3"),
        ("AcmeWeb01",   "192.168.4.45"),
        ("AcmeWks1001", "192.168.4.100"),
    ]

    for name, ip in a_records:
        create_a_record(name, ip, domain)
        create_ptr_record(ip, f"{name}.{domain}.", reverse_zone)

    # --- CNAME Records ---
    cname_records = [
        ("testweb", f"AcmeWeb01.{domain}."),
        ("b2b",     f"AcmeWeb01.{domain}."),
        ("www",     f"AcmeWeb01.{domain}."),
    ]

    for alias, target in cname_records:
        create_cname_record(alias, target, domain)

    # --- MX Record ---
    create_mx_record(f"AcmePDC01.{domain}.", domain, preference=10)

    # --- Flush cache ---
    flush_dns_cache()

    # --- Verify key records ---
    verify_record("AcmeWeb01", domain)
    verify_record("testweb", domain)

    log.info("\n[DNS] DNS record configuration COMPLETE.\n")