from utils.powershell_runner import run_ps
from config_loader import get_domain_join, get_domain_config


DC_VM = "ACME-DC01"


# ------------------------------------------------
# Helper: Run PowerShell inside a VM
# ------------------------------------------------

def run_on_vm(vm_name, ps_script):
    wrapped = f"""
Invoke-Command -VMName "{vm_name}" -ScriptBlock {{
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


# ------------------------------------------------
# Check if machine is already domain joined
# ------------------------------------------------

def is_domain_joined(vm_name):
    print(f"[JOIN] Checking if {vm_name} is already domain joined...")

    ps = """
(Get-WmiObject Win32_ComputerSystem).PartOfDomain
"""

    result = run_on_vm(vm_name, ps)

    if not result:
        return False

    return result.strip().lower() == "true"


# ------------------------------------------------
# Wait for DC availability
# ------------------------------------------------

def wait_for_dc(domain_name, timeout=600):
    print("[JOIN] Waiting for domain controller...")

    import time
    start = time.time()

    while time.time() - start < timeout:
        try:
            ps = f"""
Resolve-DnsName "{domain_name}" -ErrorAction Stop
"""
            result = run_on_vm("ACME-WS01", ps)

            if result:
                print("[JOIN] Domain is reachable.")
                return True
        except Exception:
            pass

        print("[JOIN] Waiting for domain...")
        time.sleep(15)

    raise TimeoutError("Domain controller not reachable.")


# ------------------------------------------------
# Join Domain
# ------------------------------------------------

def join_machine(vm_name, domain_name):
    print(f"[JOIN] Joining {vm_name} to domain {domain_name}")

    ps = f"""
$secpass = ConvertTo-SecureString "Password123!" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("Administrator@{domain_name}", $secpass)

Add-Computer `
    -DomainName "{domain_name}" `
    -Credential $cred `
    -Force `
    -ErrorAction Stop

Restart-Computer -Force
"""
    run_on_vm(vm_name, ps)


# ------------------------------------------------
# Wait for machine after reboot
# ------------------------------------------------

def wait_for_vm(vm_name, timeout=600):
    print(f"[JOIN] Waiting for {vm_name} to come back online...")

    import time
    start = time.time()

    while time.time() - start < timeout:
        try:
            ps = "hostname"
            result = run_on_vm(vm_name, ps)

            if result:
                print(f"[JOIN] {vm_name} is online.")
                return True
        except Exception:
            pass

        print(f"[JOIN] Waiting for {vm_name}...")
        time.sleep(15)

    raise TimeoutError(f"{vm_name} did not come back online.")


# ------------------------------------------------
# Move Computer to OU
# ------------------------------------------------

def move_to_ou(vm_name, target_ou, domain_name):
    print(f"[JOIN] Moving {vm_name} to OU {target_ou}")

    # Convert OU path → DN format
    # CorporateOffice/Computers → OU=Computers,OU=CorporateOffice,DC=ad,DC=acme,DC=edu
    ou_parts = target_ou.split("/")
    ou_dn = ",".join([f"OU={part}" for part in reversed(ou_parts)])

    domain_dn = ",".join([f"DC={x}" for x in domain_name.split(".")])

    full_dn = f"{ou_dn},{domain_dn}"

    ps = f"""
Import-Module ActiveDirectory

$comp = Get-ADComputer "{vm_name}"
Move-ADObject -Identity $comp.DistinguishedName -TargetPath "{full_dn}"
"""
    run_on_vm(DC_VM, ps)


# ------------------------------------------------
# Force Group Policy Update
# ------------------------------------------------

def force_gpupdate(vm_name):
    print(f"[JOIN] Forcing Group Policy update on {vm_name}")

    ps = """
gpupdate /force
"""
    run_on_vm(vm_name, ps)


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def join_workstations_to_domain():
    join_config = get_domain_join()
    domain_config = get_domain_config()

    domain_name = domain_config.get("name", "ad.acme.edu")
    workstations = join_config.get("workstations", [])
    target_ou = join_config.get("target_ou", "CorporateOffice/Computers")

    print("\n[JOIN] Starting domain join process...\n")

    for vm in workstations:

        # Skip if already joined
        if is_domain_joined(vm):
            print(f"[JOIN] {vm} already joined. Skipping.")
            continue

        # Wait for DC
        wait_for_dc(domain_name)

        # Join domain
        join_machine(vm, domain_name)

        # Wait for reboot
        wait_for_vm(vm)

        # Move to OU
        move_to_ou(vm, target_ou, domain_name)

        # Apply policies
        force_gpupdate(vm)

    print("\n[JOIN] Domain join COMPLETE.\n")