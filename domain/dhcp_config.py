from utils.powershell_runner import run_ps
from config_loader import get_dhcp_config


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
# Check if DHCP already configured
# ------------------------------------------------

def is_dhcp_configured(scope_name):
    print("[DHCP] Checking existing configuration...")

    ps = f"""
$scope = Get-DhcpServerv4Scope -ErrorAction SilentlyContinue |
    Where-Object {{$_.Name -eq "{scope_name}"}}

if ($scope) {{ "True" }} else {{ "False" }}
"""

    result = run_on_dc(ps)

    if not result:
        return False

    return result.strip().lower() == "true"


# ------------------------------------------------
# Install DHCP Role
# ------------------------------------------------

def install_dhcp_role():
    print("[DHCP] Installing DHCP role...")

    ps = """
Install-WindowsFeature DHCP -IncludeManagementTools
"""
    run_on_dc(ps)


# ------------------------------------------------
# Authorize DHCP Server
# ------------------------------------------------

def authorize_dhcp():
    print("[DHCP] Authorizing DHCP server in AD...")

    ps = """
Add-DhcpServerInDC -ErrorAction SilentlyContinue
"""
    run_on_dc(ps)


# ------------------------------------------------
# Create Scope
# ------------------------------------------------

def create_scope(config):
    print("[DHCP] Creating scope...")

    scope_name = config["scope_name"]
    start_ip = config["start_ip"]
    end_ip = config["end_ip"]
    subnet_mask = config["subnet_mask"]

    ps = f"""
Add-DhcpServerv4Scope `
    -Name "{scope_name}" `
    -StartRange {start_ip} `
    -EndRange {end_ip} `
    -SubnetMask {subnet_mask} `
    -ErrorAction SilentlyContinue
"""
    run_on_dc(ps)


# ------------------------------------------------
# Configure Scope Options
# ------------------------------------------------

def configure_scope_options(config):
    print("[DHCP] Setting scope options...")

    gateway = config["router"]
    dns = config["dns_server"]
    domain = config["dns_domain"]

    ps = f"""
Set-DhcpServerv4OptionValue `
    -Router {gateway} `
    -DnsServer {dns} `
    -DnsDomain "{domain}"
"""
    run_on_dc(ps)


# ------------------------------------------------
# Add Exclusions
# ------------------------------------------------

def add_exclusions(config):
    exclusions = config.get("exclusions", [])

    if not exclusions:
        return

    print("[DHCP] Adding exclusions...")

    for ex in exclusions:
        start, end = ex.split("-")

        ps = f"""
Add-DhcpServerv4ExclusionRange `
    -StartRange {start} `
    -EndRange {end} `
    -ErrorAction SilentlyContinue
"""
        run_on_dc(ps)


# ------------------------------------------------
# Verify DHCP
# ------------------------------------------------

def verify_dhcp(scope_name):
    print("[DHCP] Verifying DHCP configuration...")

    ps = f"""
$scope = Get-DhcpServerv4Scope |
    Where-Object {{$_.Name -eq "{scope_name}"}}

if ($scope) {{ $scope.Name }} else {{ "" }}
"""

    result = run_on_dc(ps)

    if not result:
        raise Exception("DHCP verification failed.")

    print(f"[DHCP] Scope confirmed: {result.strip()}")


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def configure_dhcp():
    config = get_dhcp_config()

    scope_name = config.get("scope_name", "AcmeBusiness")

    print("\n[DHCP] Starting DHCP configuration...\n")

    # --- Skip if already configured ---
    if is_dhcp_configured(scope_name):
        print("[DHCP] DHCP already configured. Skipping.")
        return

    install_dhcp_role()
    authorize_dhcp()
    create_scope(config)
    add_exclusions(config)
    configure_scope_options(config)
    verify_dhcp(scope_name)

    print("\n[DHCP] DHCP configuration COMPLETE.\n")