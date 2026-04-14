from utils.powershell_runner import run_ps


# ------------------------------------------------
# Helper: Parse permission string
# Example: "Everyone:FullControl"
# ------------------------------------------------

def _parse_permissions(permission_string):
    identity, access = permission_string.split(":")
    return identity.strip(), access.strip()


# ------------------------------------------------
# Create Folder + Share
# ------------------------------------------------

def create_share(share_config):
    """
    Creates a folder and SMB share on the domain controller.

    share_config example:
    {
        "name": "Users$",
        "path": "E:\\Users$",
        "share_permissions": "Everyone:FullControl"
    }
    """

    name = share_config["name"]
    path = share_config["path"]
    perm_string = share_config["share_permissions"]

    identity, access = _parse_permissions(perm_string)

    print(f"[SHARE] Creating {name} at {path}")

    ps = f"""
$shareName = "{name}"
$path = "{path}"
$identity = "{identity}"
$access = "{access}"

# Create folder if it doesn't exist
if (-not (Test-Path $path)) {{
    New-Item -Path $path -ItemType Directory -Force
}}

# Create SMB Share if it doesn't exist
if (-not (Get-SmbShare -Name $shareName -ErrorAction SilentlyContinue)) {{
    New-SmbShare `
        -Name $shareName `
        -Path $path `
        -FullAccess $identity
}}

# Set NTFS permissions
$acl = Get-Acl $path
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $identity, $access, "ContainerInherit,ObjectInherit", "None", "Allow"
)
$acl.SetAccessRule($rule)
Set-Acl $path $acl
"""

    run_ps(ps)


# ------------------------------------------------
# Bulk Share Creation
# ------------------------------------------------

def create_all_shares(config):
    """
    Reads JSON config and creates all shares.
    """

    shares = config.get("shared_folders", [])

    if not shares:
        print("[SHARE] No shares defined in config.")
        return

    print("\n[SHARE] Creating all shared folders...\n")

    for share in shares:
        create_share(share)


# ------------------------------------------------
# Home Directory Creation
# ------------------------------------------------

def create_home_directories(config):
    """
    Creates home directories for users.

    Example JSON:
    {
        "user": "SecTest",
        "path": "\\\\AcmePDC01\\Users$\\SecTest"
    }
    """

    homes = config.get("home_directories", [])

    if not homes:
        print("[SHARE] No home directories defined.")
        return

    print("\n[SHARE] Creating home directories...\n")

    for home in homes:
        username = home["user"]

        # Convert UNC path → local path
        # \\AcmePDC01\Users$\SecTest → E:\Users$\SecTest
        unc_path = home["path"]
        local_path = unc_path.replace("\\\\AcmePDC01\\Users$", "E:\\Users$")

        print(f"[HOME] Creating home directory for {username}")

        ps = f"""
$path = "{local_path}"
$user = "{username}"

if (-not (Test-Path $path)) {{
    New-Item -Path $path -ItemType Directory -Force
}}

# Set permissions so only user has access
$acl = Get-Acl $path

$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $user, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow"
)

$acl.SetAccessRule($rule)
Set-Acl $path $acl
"""

        run_ps(ps)


# ------------------------------------------------
# Main Entry Point
# ------------------------------------------------

def setup_shares(config):
    """
    Full share deployment pipeline.
    """

    create_all_shares(config)
    create_home_directories(config)