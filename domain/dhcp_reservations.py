from utils.powershell_runner import run_ps
from config_loader import get_dhcp_config, get_dc_name, get_admin_password
from utils.logger import get_logger

log=get_logger("dhcp_reservations"); DC_VM=get_dc_name(); ADMIN_PASS=get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def _scope_id(cfg):
    o=cfg.get("start_ip","192.168.4.100").split("."); return f"{o[0]}.{o[1]}.{o[2]}.0"

def create_reservation(scope_id,ip,mac,name,description=""):
    log.info(f"[DHCP-RES] {ip} -> {name}")
    _run_on_dc(f"""
$e=Get-DhcpServerv4Reservation -ScopeId "{scope_id}" -EA SilentlyContinue|Where-Object{{$_.IPAddress -eq "{ip}"}}
if(-not $e){{Add-DhcpServerv4Reservation -ScopeId "{scope_id}" -IPAddress "{ip}" -ClientId "{mac}" -Name "{name}" -Description "{description}"}}
""")

def configure_wins(primary):
    _run_on_dc(f"Set-DhcpServerv4OptionValue -OptionId 44 -Value {primary} -EA SilentlyContinue; Set-DhcpServerv4OptionValue -OptionId 46 -Value 8 -EA SilentlyContinue")

def configure_dhcp_reservations():
    cfg=get_dhcp_config(); sid=_scope_id(cfg)
    log.info("\n[DHCP-RES] Configuring reservations...\n")
    for r in [
        {"ip":"192.168.4.1", "mac":"00-15-5D-01-01-01","name":"AcmeRtr01"},
        {"ip":"192.168.4.3", "mac":"00-15-5D-01-01-03","name":"AcmePDC01"},
        {"ip":"192.168.4.4", "mac":"00-15-5D-01-01-04","name":"AcmePDC02"},
        {"ip":"192.168.4.45","mac":"00-15-5D-01-01-45","name":"AcmeWeb01"},
    ]: create_reservation(sid,r["ip"],r["mac"],r["name"])
    configure_wins("192.168.4.3")
    log.info("\n[DHCP-RES] COMPLETE.\n")