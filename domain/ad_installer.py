from utils.powershell_runner import run_ps
from config_loader import get_domain_config


DC_VM = "ACME-DC01"


# ------------------------------------------------
# Helper: Run PowerShell inside VM
# ------------------------------------------------

def run_on_dc(ps_script):
    wrapped = f"""
Invoke-Command -VMName "{DC_VM}" -ScriptBlock {{
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


# ------------------------------------------------
# Check if AD is already installed
# ------------------------------------------------

def is_ad_installed():
    print("[AD] Checking if Active Directory is already installed...")

    ps = """
$feature = Get-WindowsFeature AD-Domain-Services
if ($feature.Installed) { "True" } else { "False" }
"""
    result = run_on_dc(ps)

    if not result:
        return False

    return result.strip().lower() == "true"


# ------------------------------------------------
# Wait for Domain Controller after reboot
# ------------------------------------------------

def wait_for_dc_ready(timeout=600):
    print("[AD] Waiting for Domain Controller to become ready...")

    import time
    start = time.time()

    while time.time() - start < timeout:
        try:
            result = run_on_dc("hostname")
            if result:
                print("[AD] DC is reachable.")
                return True
        except Exception:
            pass

        print("[AD] Waiting for DC...")
        time.sleep(15)

    raise TimeoutError("Domain Controller did not come back online in time.")


# ------------------------------------------------
# Verify AD is functional
# ------------------------------------------------

def verify_ad():
    print("[AD] Verifying Active Directory...")

    ps = """
Import-Module ActiveDirectory
(Get-ADDomain).Name
"""
    result = run_on_dc(ps)

    if not result:
        raise Exception("Active Directory verification failed.")

    print(f"[AD] Domain confirmed: {result.strip()}")


# ------------------------------------------------
# Install Active Directory
# ------------------------------------------------

def install_active_directory():
    config = get_domain_config()

    # config_loader returns keys "name" and "netbios"
    domain_name = config.get("name", "ad.acme.edu")
    netbios = config.get("netbios", "ACME")
    safe_mode_pass = "Password123!"

    print(f"\n[AD] Installing Active Directory: {domain_name}\n")

    if is_ad_installed():
        print("[AD] Active Directory already installed. Skipping.")
        return

    print("[AD] Installing AD DS role...")

    ps_install = """
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools
"""
    run_on_dc(ps_install)

    print("[AD] Promoting to Domain Controller...")

    ps_promote = f"""
Import-Module ADDSDeployment

$securePass = ConvertTo-SecureString "{safe_mode_pass}" -AsPlainText -Force

Install-ADDSForest `
    -DomainName "{domain_name}" `
    -DomainNetbiosName "{netbios}" `
    -SafeModeAdministratorPassword $securePass `
    -InstallDNS `
    -Force `
    -NoRebootOnCompletion

Restart-Computer -Force
"""
    run_on_dc(ps_promote)

    wait_for_dc_ready()
    verify_ad()

    print("\n[AD] Active Directory installation COMPLETE.\n")