from utils.powershell_runner import run_ps
from config_loader import get_dhcp_config, get_dc_name, get_admin_password
from utils.logger import get_logger

log       = get_logger("dhcp_config")
DC_VM     = get_dc_name()
ADMIN_PASS= get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def is_dhcp_configured(scope_name):
    r=_run_on_dc(f'$s=Get-DhcpServerv4Scope -EA SilentlyContinue|Where-Object{{$_.Name -eq "{scope_name}"}};if($s){{"True"}}else{{"False"}}')
    return bool(r) and r.strip().lower()=="true"

def configure_dhcp():
    cfg=get_dhcp_config(); scope_name=cfg.get("scope_name","AcmeBusiness")
    log.info(f"\n[DHCP] Configuring: {scope_name}\n")
    if is_dhcp_configured(scope_name): log.info("[DHCP] Already configured."); return
    _run_on_dc("Install-WindowsFeature DHCP -IncludeManagementTools")
    _run_on_dc("Add-DhcpServerInDC -ErrorAction SilentlyContinue")
    _run_on_dc(f'Add-DhcpServerv4Scope -Name "{scope_name}" -StartRange {cfg.get("start_ip","192.168.4.100")} -EndRange {cfg.get("end_ip","192.168.4.200")} -SubnetMask {cfg.get("subnet_mask","255.255.255.0")} -EA SilentlyContinue')
    for ex in cfg.get("exclusions",[]):
        s,e=ex.split("-")
        _run_on_dc(f"Add-DhcpServerv4ExclusionRange -StartRange {s.strip()} -EndRange {e.strip()} -EA SilentlyContinue")
    _run_on_dc(f'Set-DhcpServerv4OptionValue -Router {cfg.get("router","192.168.4.1")} -DnsServer {cfg.get("dns_server","192.168.4.3")} -DnsDomain "{cfg.get("dns_domain","ad.acme.edu")}"')
    r=_run_on_dc(f'$s=Get-DhcpServerv4Scope|Where-Object{{$_.Name -eq "{scope_name}"}};if($s){{$s.Name}}else{{""}}')
    if not r or not r.strip(): raise RuntimeError("DHCP verification failed.")
    log.info(f"[DHCP] Scope confirmed: {r.strip()}")
    log.info("\n[DHCP] COMPLETE.\n")