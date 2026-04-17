from utils.powershell_runner import run_ps
from config_loader import get_domain_config, get_dc_name, get_admin_password
from utils.logger import get_logger

log=get_logger("dns_records"); DC_VM=get_dc_name(); ADMIN_PASS=get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def create_a_record(name,ip,zone):
    _run_on_dc(f'Import-Module DnsServer; if(-not(Get-DnsServerResourceRecord -ZoneName "{zone}" -Name "{name}" -RRType A -EA SilentlyContinue)){{Add-DnsServerResourceRecordA -ZoneName "{zone}" -Name "{name}" -IPv4Address "{ip}"}}')

def create_cname_record(alias,target,zone):
    _run_on_dc(f'Import-Module DnsServer; if(-not(Get-DnsServerResourceRecord -ZoneName "{zone}" -Name "{alias}" -RRType CNAME -EA SilentlyContinue)){{Add-DnsServerResourceRecordCName -ZoneName "{zone}" -Name "{alias}" -HostNameAlias "{target}"}}')

def create_mx_record(mail_server,zone,preference=10):
    _run_on_dc(f'Import-Module DnsServer; if(-not(Get-DnsServerResourceRecord -ZoneName "{zone}" -Name "@" -RRType MX -EA SilentlyContinue)){{Add-DnsServerResourceRecordMX -ZoneName "{zone}" -Name "@" -MailExchange "{mail_server}" -Preference {preference}}}')

def create_reverse_lookup_zone(network_id):
    octets=network_id.split("."); zn=".".join(reversed(octets))+".in-addr.arpa"
    _run_on_dc(f'Import-Module DnsServer; if(-not(Get-DnsServerZone -Name "{zn}" -EA SilentlyContinue)){{Add-DnsServerPrimaryZone -NetworkID "{network_id}.0/24" -ReplicationScope "Forest"}}')
    return zn

def create_ptr_record(ip,fqdn,zone_name):
    last=ip.split(".")[-1]
    _run_on_dc(f'Import-Module DnsServer; if(-not(Get-DnsServerResourceRecord -ZoneName "{zone_name}" -Name "{last}" -RRType PTR -EA SilentlyContinue)){{Add-DnsServerResourceRecordPtr -ZoneName "{zone_name}" -Name "{last}" -PtrDomainName "{fqdn}"}}')

def configure_dns_records():
    domain=get_domain_config()["name"]
    log.info(f"\n[DNS-RECORDS] Configuring for {domain}\n")
    rev=create_reverse_lookup_zone("192.168.4")
    for name,ip in [("AcmeRtr01","192.168.4.1"),("AcmePDC01","192.168.4.3"),
                    ("AcmePDC02","192.168.4.4"),("AcmeWeb01","192.168.4.45"),("AcmeWks1001","192.168.4.100")]:
        create_a_record(name,ip,domain); create_ptr_record(ip,f"{name}.{domain}.",rev)
    for alias,target in [("testweb",f"AcmeWeb01.{domain}."),("b2b",f"AcmeWeb01.{domain}."),("www",f"AcmeWeb01.{domain}.")]:
        create_cname_record(alias,target,domain)
    create_mx_record(f"AcmePDC01.{domain}.",domain)
    _run_on_dc("Clear-DnsServerCache -Force")
    log.info("\n[DNS-RECORDS] COMPLETE.\n")