from utils.powershell_runner import run_ps
from config_loader import get_network_config


ROUTER_VM = "ACME-Router"
DC_VM = "ACME-DC01"


# ------------------------------------------------
# Helper: Run PowerShell inside VM
# ------------------------------------------------

def run_on_vm(vm_name, ps_script):
    wrapped = f"""
Invoke-Command -VMName "{vm_name}" -ScriptBlock {{
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


# ------------------------------------------------
# Configure Router Networking (NAT + Routing)
# ------------------------------------------------

def configure_router():
    print("\n[NET] Configuring router (NAT + Routing)...\n")

    net = get_network_config()

    gateway = net.get("gateway", "192.168.4.1")
    subnet = net.get("subnet", "192.168.4.0/24")

    ps = f"""
# Install Routing role
Install-WindowsFeature RemoteAccess -IncludeManagementTools
Install-WindowsFeature Routing

# Enable NAT
Import-Module RemoteAccess
Import-Module Routing

# Get adapters
$internal = Get-NetAdapter | Where-Object {{$_.Name -like "*Ethernet*"}} | Select-Object -First 1
$external = Get-NetAdapter | Where-Object {{$_.Name -like "*External*"}} | Select-Object -First 1

# Assign static IP to internal NIC
New-NetIPAddress -InterfaceIndex $internal.ifIndex -IPAddress "{gateway}" -PrefixLength 24 -ErrorAction SilentlyContinue

# Enable NAT
if (-not (Get-NetNat -ErrorAction SilentlyContinue)) {{
    New-NetNat -Name "ACMENAT" -InternalIPInterfaceAddressPrefix "{subnet}"
}}

# Enable routing
Set-Service RemoteAccess -StartupType Automatic
Start-Service RemoteAccess
"""

    run_on_vm(ROUTER_VM, ps)

    print("[NET] Router configured.\n")


# ------------------------------------------------
# Configure Domain Controller Network
# ------------------------------------------------

def configure_domain_controller_network():
    print("[NET] Configuring Domain Controller network...")

    net = get_network_config()

    ip = net.get("dns_primary", "192.168.4.3")
    gateway = net.get("gateway", "192.168.4.1")

    ps = f"""
$adapter = Get-NetAdapter | Where-Object {{$_.Status -eq "Up"}} | Select-Object -First 1

# Set static IP
New-NetIPAddress `
    -InterfaceIndex $adapter.ifIndex `
    -IPAddress "{ip}" `
    -PrefixLength 24 `
    -DefaultGateway "{gateway}" `
    -ErrorAction SilentlyContinue

# Set DNS (self for DC)
Set-DnsClientServerAddress `
    -InterfaceIndex $adapter.ifIndex `
    -ServerAddresses ("{ip}")
"""

    run_on_vm(DC_VM, ps)

    print("[NET] Domain Controller network configured.\n")


# ------------------------------------------------
# Configure Workstation Network (DHCP)
# ------------------------------------------------

def configure_workstation_network(vm_name):
    print(f"[NET] Configuring {vm_name} for DHCP...")

    ps = """
$adapter = Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | Select-Object -First 1

# Enable DHCP
Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ResetServerAddresses
"""

    run_on_vm(vm_name, ps)

    print(f"[NET] {vm_name} set to DHCP.\n")


# ------------------------------------------------
# Wait for Network Availability
# ------------------------------------------------

def wait_for_network(vm_name, timeout=300):
    print(f"[NET] Waiting for network on {vm_name}...")

    import time
    start = time.time()

    while time.time() - start < timeout:
        try:
            ps = "Test-Connection -ComputerName 8.8.8.8 -Count 1 -Quiet"
            result = run_on_vm(vm_name, ps)

            if result and result.strip().lower() == "true":
                print(f"[NET] {vm_name} has internet connectivity.")
                return True

        except Exception:
            pass

        print(f"[NET] Waiting on {vm_name} network...")
        time.sleep(10)

    raise TimeoutError(f"{vm_name} network not ready.")


# ------------------------------------------------
# MAIN ENTRY
# ------------------------------------------------

def configure_networking(workstations):
    print("\n========== NETWORK CONFIGURATION ==========\n")

    # Router first (critical)
    configure_router()

    # Domain Controller
    configure_domain_controller_network()

    # Workstations
    for ws in workstations:
        configure_workstation_network(ws)

    print("\n[NET] Base network configuration complete.\n")