from utils.powershell_runner import run_ps
from config_loader import get_dhcp_config
from utils.logger import get_logger

log = get_logger("dhcp_reservations")

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
# Get scope ID from config
# ------------------------------------------------

def _get_scope_id(config):
    """Derives the scope ID (network address) from the start IP."""
    start_ip = config.get("start_ip", "192.168.4.100")
    octets = start_ip.split(".")
    return f"{octets[0]}.{octets[1]}.{octets[2]}.0"


# ------------------------------------------------
# Create a single reservation
# ------------------------------------------------

def create_reservation(scope_id, ip, mac, name, description=""):
    """
    Creates a DHCP reservation binding an IP to a MAC address.

    mac format: "00-11-22-33-44-55"
    """

    log.info(f"[DHCP-RES] Reserving {ip} for {name} ({mac})")

    ps = f"""
$scopeId  = "{scope_id}"
$ip       = "{ip}"
$mac      = "{mac}"
$name     = "{name}"

$existing = Get-DhcpServerv4Reservation `
    -ScopeId $scopeId `
    -ErrorAction SilentlyContinue |
    Where-Object {{ $_.IPAddress -eq $ip }}

if (-not $existing) {{
    Add-DhcpServerv4Reservation `
        -ScopeId $scopeId `
        -IPAddress $ip `
        -ClientId $mac `
        -Name $name `
        -Description "{description}" `
        -ErrorAction Stop

    Write-Output "Reserved $ip for $name"
}} else {{
    Write-Output "Reservation already exists for $ip"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Remove a reservation
# ------------------------------------------------

def remove_reservation(scope_id, ip):
    log.info(f"[DHCP-RES] Removing reservation for {ip}")

    ps = f"""
Remove-DhcpServerv4Reservation `
    -ScopeId "{scope_id}" `
    -IPAddress "{ip}" `
    -ErrorAction SilentlyContinue
"""
    run_on_dc(ps)


# ------------------------------------------------
# Configure WINS servers on scope
# ------------------------------------------------

def configure_wins(primary_wins, secondary_wins=None):
    """
    Sets WINS server options on the DHCP scope.
    Option 44 = WINS/NBNS, Option 46 = Node Type (0x8 = H-node)
    """

    log.info(f"[DHCP-RES] Configuring WINS: primary={primary_wins}")

    wins_list = primary_wins
    if secondary_wins:
        wins_list = f"{primary_wins}, {secondary_wins}"

    ps = f"""
# Option 44: WINS/NBNS server
Set-DhcpServerv4OptionValue `
    -OptionId 44 `
    -Value {primary_wins} `
    -ErrorAction SilentlyContinue

# Option 46: WINS/NBT node type (8 = H-node: unicast first, then broadcast)
Set-DhcpServerv4OptionValue `
    -OptionId 46 `
    -Value 8 `
    -ErrorAction SilentlyContinue

Write-Output "WINS options configured."
"""
    run_on_dc(ps)


# ------------------------------------------------
# List all current reservations
# ------------------------------------------------

def list_reservations(scope_id):
    log.info(f"[DHCP-RES] Listing reservations in scope {scope_id}")

    ps = f"""
Get-DhcpServerv4Reservation -ScopeId "{scope_id}" |
    Select-Object IPAddress, ClientId, Name, Description |
    Format-Table -AutoSize
"""
    result = run_on_dc(ps)
    if result:
        print(result)
    return result


# ------------------------------------------------
# Verify a reservation exists
# ------------------------------------------------

def verify_reservation(scope_id, ip):
    ps = f"""
$r = Get-DhcpServerv4Reservation -ScopeId "{scope_id}" -ErrorAction SilentlyContinue |
     Where-Object {{ $_.IPAddress -eq "{ip}" }}
if ($r) {{ "True" }} else {{ "False" }}
"""
    result = run_on_dc(ps)
    return result and result.strip().lower() == "true"


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def configure_dhcp_reservations():
    config = get_dhcp_config()
    scope_id = _get_scope_id(config)

    log.info("\n[DHCP-RES] Configuring DHCP reservations...\n")

    # Static reservations for infrastructure servers
    # MACs are placeholders — in a real lab these come from the VM NICs
    reservations = [
        {
            "ip":          "192.168.4.1",
            "mac":         "00-15-5D-01-01-01",
            "name":        "AcmeRtr01",
            "description": "Lab Router - Static"
        },
        {
            "ip":          "192.168.4.3",
            "mac":         "00-15-5D-01-01-03",
            "name":        "AcmePDC01",
            "description": "Primary Domain Controller - Static"
        },
        {
            "ip":          "192.168.4.45",
            "mac":         "00-15-5D-01-01-45",
            "name":        "AcmeWeb01",
            "description": "Ubuntu Web Server - Static"
        },
    ]

    for r in reservations:
        create_reservation(
            scope_id=scope_id,
            ip=r["ip"],
            mac=r["mac"],
            name=r["name"],
            description=r["description"]
        )

    # Configure WINS to point to the DC (NetBIOS name resolution)
    configure_wins(primary_wins="192.168.4.3")

    # List final state
    list_reservations(scope_id)

    log.info("\n[DHCP-RES] DHCP reservation configuration COMPLETE.\n")