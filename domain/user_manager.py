from utils.powershell_runner import run_ps
from config_loader import get_users, get_domain_config, get_dc_name, get_admin_password

DC_VM=get_dc_name(); ADMIN_PASS=get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def create_users_and_groups():
    users=get_users(); cfg=get_domain_config()
    domain_dn=",".join([f"DC={p}" for p in cfg["name"].split(".")])
    print("Creating users and groups...")
    unique_groups={g for u in users for g in u.get("groups",[])}
    for g in unique_groups:
        _create_global_group(g,domain_dn); _create_domain_local_group(g,domain_dn); _link_agdlp(g)
    for u in users: _create_user(u,domain_dn)
    for u in users:
        for g in u.get("groups",[]): _add_to_group(u["username"],g)

def _create_global_group(g,dn):
    name=f"GG_{g}"
    _run_on_dc(f'Import-Module ActiveDirectory; if(-not(Get-ADGroup -Filter "Name -eq \'{name}\'" -EA SilentlyContinue)){{New-ADGroup -Name "{name}" -GroupScope Global -Path "{dn}"}}')

def _create_domain_local_group(g,dn):
    name=f"DL_{g}"
    _run_on_dc(f'Import-Module ActiveDirectory; if(-not(Get-ADGroup -Filter "Name -eq \'{name}\'" -EA SilentlyContinue)){{New-ADGroup -Name "{name}" -GroupScope DomainLocal -Path "{dn}"}}')

def _link_agdlp(g):
    _run_on_dc(f'Import-Module ActiveDirectory; Add-ADGroupMember -Identity "DL_{g}" -Members "GG_{g}" -EA SilentlyContinue')

def _create_user(user,domain_dn):
    un=user["username"]; pw=user.get("password","Password123!")
    fn=user.get("firstname",un); ln=user.get("lastname","")
    disabled=user.get("disabled",False); pne=user.get("password_never_expires",False)
    ou_path=user.get("ou","")
    ou_dn=domain_dn
    if ou_path:
        for part in reversed(ou_path.split("/")): ou_dn=f"OU={part},{ou_dn}"
    enabled="$true" if not disabled else "$false"
    pneflag="$true" if pne else "$false"
    upn_domain=domain_dn.replace("DC=","").replace(",",".")
    _run_on_dc(f"""
Import-Module ActiveDirectory
if(-not(Get-ADUser -Filter "SamAccountName -eq '{un}'" -EA SilentlyContinue)){{
    $sp=ConvertTo-SecureString "{pw}" -AsPlainText -Force
    New-ADUser -Name "{fn} {ln}" -GivenName "{fn}" -Surname "{ln}" -SamAccountName "{un}" `
        -UserPrincipalName "{un}@{upn_domain}" -AccountPassword $sp `
        -Enabled {enabled} -PasswordNeverExpires {pneflag} -Path "{ou_dn}"
    Write-Output "Created: {un}"
}}
""")

def _add_to_group(username,group):
    _run_on_dc(f'Import-Module ActiveDirectory; Add-ADGroupMember -Identity "GG_{group}" -Members "{username}" -EA SilentlyContinue')