from utils.powershell_runner import run_ps
from config_loader import get_ous, get_domain_config


def create_organizational_units():
    """
    Creates Organizational Units based on config.
    Supports nested OUs using path-style definitions.
    Example: "CorporateOffice/Users/SecTest"
    """

    ous = get_ous()
    domain_config = get_domain_config()

    domain_name = domain_config.get("name", "ad.acme.edu")
    domain_dn = ",".join([f"DC={part}" for part in domain_name.split(".")])

    print("Creating Organizational Units...")

    # Sort OUs so parents are created before children
    ous_sorted = sorted(ous, key=lambda x: x.count("/"))

    for ou_path in ous_sorted:
        create_single_ou(ou_path, domain_dn)


def create_single_ou(ou_path, domain_dn):
    """
    Creates a single OU, ensuring parent exists.
    """

    parts = ou_path.split("/")
    ou_name = parts[-1]

    # Build distinguished name (DN)
    parent_dn = domain_dn
    for part in reversed(parts[:-1]):
        parent_dn = f"OU={part},{parent_dn}"

    full_dn = f"OU={ou_name},{parent_dn}"

    print(f"Ensuring OU exists: {full_dn}")

    ps = f"""
Import-Module ActiveDirectory

$ouDN = "{full_dn}"

if (-not (Get-ADOrganizationalUnit -Filter "DistinguishedName -eq '$ouDN'" -ErrorAction SilentlyContinue)) {{

    New-ADOrganizationalUnit `
        -Name "{ou_name}" `
        -Path "{parent_dn}" `
        -ProtectedFromAccidentalDeletion $false

    Write-Output "Created OU: {ou_name}"
}}
else {{
    Write-Output "OU already exists: {ou_name}"
}}
"""

    run_ps(ps)