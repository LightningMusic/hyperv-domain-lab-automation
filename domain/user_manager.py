from utils.powershell_runner import run_ps
from config_loader import get_users, get_domain_config


def create_users_and_groups():
    """
    Creates:
    - Global Groups (GG_)
    - Domain Local Groups (DL_)
    - Users
    - AGDLP relationships
    """

    users = get_users()
    domain_config = get_domain_config()

    domain_name = domain_config.get("name", "ad.acme.edu")
    domain_dn = ",".join([f"DC={part}" for part in domain_name.split(".")])

    print("Creating users and groups...")

    # Step 1: Collect all unique group names
    unique_groups = set()
    for user in users:
        for group in user.get("groups", []):
            unique_groups.add(group)

    # Step 2: Create Global + Domain Local groups
    for group in unique_groups:
        create_global_group(group, domain_dn)
        create_domain_local_group(group, domain_dn)
        link_agdlp(group)

    # Step 3: Create Users
    for user in users:
        create_user(user, domain_dn)

    # Step 4: Add users to global groups
    for user in users:
        for group in user.get("groups", []):
            add_user_to_global_group(user["username"], group)


# ------------------------------------------------
# GROUP CREATION
# ------------------------------------------------

def create_global_group(group_name, domain_dn):
    gg_name = f"GG_{group_name}"

    print(f"Ensuring Global Group exists: {gg_name}")

    ps = f"""
Import-Module ActiveDirectory

if (-not (Get-ADGroup -Filter "Name -eq '{gg_name}'" -ErrorAction SilentlyContinue)) {{

    New-ADGroup `
        -Name "{gg_name}" `
        -GroupScope Global `
        -Path "{domain_dn}"

    Write-Output "Created Global Group: {gg_name}"
}}
"""

    run_ps(ps)


def create_domain_local_group(group_name, domain_dn):
    dl_name = f"DL_{group_name}"

    print(f"Ensuring Domain Local Group exists: {dl_name}")

    ps = f"""
Import-Module ActiveDirectory

if (-not (Get-ADGroup -Filter "Name -eq '{dl_name}'" -ErrorAction SilentlyContinue)) {{

    New-ADGroup `
        -Name "{dl_name}" `
        -GroupScope DomainLocal `
        -Path "{domain_dn}"

    Write-Output "Created Domain Local Group: {dl_name}"
}}
"""

    run_ps(ps)


def link_agdlp(group_name):
    gg_name = f"GG_{group_name}"
    dl_name = f"DL_{group_name}"

    print(f"Linking AGDLP: {gg_name} -> {dl_name}")

    ps = f"""
Import-Module ActiveDirectory

Add-ADGroupMember `
    -Identity "{dl_name}" `
    -Members "{gg_name}" `
    -ErrorAction SilentlyContinue
"""

    run_ps(ps)


# ------------------------------------------------
# USER CREATION
# ------------------------------------------------

def create_user(user, domain_dn):
    username = user["username"]
    password = user.get("password", "Password123!")
    ou_path = user.get("ou", "")
    firstname = user.get("firstname", username)
    lastname = user.get("lastname", "")
    disabled = user.get("disabled", False)
    pw_never_expires = user.get("password_never_expires", False)

    # Convert OU path → DN
    ou_dn = domain_dn
    if ou_path:
        parts = ou_path.split("/")
        for part in reversed(parts):
            ou_dn = f"OU={part},{ou_dn}"

    enabled_flag = "$true" if not disabled else "$false"
    pw_never_flag = "$true" if pw_never_expires else "$false"

    print(f"Ensuring user exists: {username}")

    ps = f"""
Import-Module ActiveDirectory

if (-not (Get-ADUser -Filter "SamAccountName -eq '{username}'" -ErrorAction SilentlyContinue)) {{

    $securePass = ConvertTo-SecureString "{password}" -AsPlainText -Force

    New-ADUser `
        -Name "{firstname} {lastname}" `
        -GivenName "{firstname}" `
        -Surname "{lastname}" `
        -SamAccountName "{username}" `
        -UserPrincipalName "{username}@{domain_dn.replace('DC=', '').replace(',', '.')}" `
        -AccountPassword $securePass `
        -Enabled {enabled_flag} `
        -PasswordNeverExpires {pw_never_flag} `
        -Path "{ou_dn}"

    Write-Output "Created user: {username}"
}}
"""
    run_ps(ps)


# ------------------------------------------------
# GROUP MEMBERSHIP
# ------------------------------------------------

def add_user_to_global_group(username, group_name):
    gg_name = f"GG_{group_name}"

    print(f"Adding {username} to {gg_name}")

    ps = f"""
Import-Module ActiveDirectory

Add-ADGroupMember `
    -Identity "{gg_name}" `
    -Members "{username}" `
    -ErrorAction SilentlyContinue
"""

    run_ps(ps)