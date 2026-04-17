from utils.powershell_runner import run_ps
from config_loader import get_ous, get_domain_config, get_dc_name, get_admin_password

DC_VM=get_dc_name(); ADMIN_PASS=get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def create_organizational_units():
    ous=get_ous(); cfg=get_domain_config()
    domain_dn=",".join([f"DC={p}" for p in cfg["name"].split(".")])
    print("Creating Organizational Units...")
    for ou_path in sorted(ous, key=lambda x: x.count("/")):
        _create_single_ou(ou_path, domain_dn)

def _create_single_ou(ou_path, domain_dn):
    parts=ou_path.split("/"); ou_name=parts[-1]
    parent_dn=domain_dn
    for part in reversed(parts[:-1]):
        parent_dn=f"OU={part},{parent_dn}"
    full_dn=f"OU={ou_name},{parent_dn}"
    print(f"Ensuring OU: {full_dn}")
    _run_on_dc(f"""
Import-Module ActiveDirectory
if(-not(Get-ADOrganizationalUnit -Filter "DistinguishedName -eq '{full_dn}'" -EA SilentlyContinue)){{
    New-ADOrganizationalUnit -Name "{ou_name}" -Path "{parent_dn}" -ProtectedFromAccidentalDeletion $false
    Write-Output "Created: {ou_name}"
}} else {{ Write-Output "Exists: {ou_name}" }}
""")