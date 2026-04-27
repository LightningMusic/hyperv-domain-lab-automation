from config_loader import get_admin_password, get_dc_name
from utils.powershell_runner import run_ps

DC_VM = get_dc_name()
ADMIN_PASS = get_admin_password()


def _run_on_dc(ps_script, return_output=False):
    wrapped = f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ErrorAction Stop -ScriptBlock {{
$ErrorActionPreference = "Stop"
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=return_output)

def _parse_perm(s):
    identity,access=s.split(":"); return identity.strip(),access.strip()


def _to_local_home_path(remote_path):
    remote_root = f"\\\\{DC_VM}\\Users$"
    if remote_path.lower().startswith(remote_root.lower()):
        suffix = remote_path[len(remote_root):].lstrip("\\")
        return f"E:\\Users$\\{suffix}" if suffix else r"E:\Users$"
    return remote_path

def create_share(share_config):
    name=share_config["name"]; path=share_config["path"]
    identity,access=_parse_perm(share_config["share_permissions"])
    print(f"[SHARE] {name} at {path}")
    _run_on_dc(f"""
if(-not(Test-Path "{path}")){{New-Item -Path "{path}" -ItemType Directory -Force}}
if(-not(Get-SmbShare -Name "{name}" -EA SilentlyContinue)){{New-SmbShare -Name "{name}" -Path "{path}" -FullAccess "{identity}"}}
$acl=Get-Acl "{path}"
$rule=New-Object System.Security.AccessControl.FileSystemAccessRule("{identity}","{access}","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($rule); Set-Acl "{path}" $acl
""")

def create_all_shares(config):
    shares=config.get("shared_folders",[])
    if not shares: print("[SHARE] No shares defined."); return
    print("\n[SHARE] Creating shared folders...\n")
    for s in shares: create_share(s)

def create_home_directories(config):
    homes=config.get("home_directories",[])
    if not homes: return
    print("\n[SHARE] Creating home directories...\n")
    for home in homes:
        username=home["user"]
        local_path=_to_local_home_path(home["path"])
        print(f"[HOME] {username}")
        _run_on_dc(f"""
if(-not(Test-Path "{local_path}")){{New-Item -Path "{local_path}" -ItemType Directory -Force}}
$acl=Get-Acl "{local_path}"
$rule=New-Object System.Security.AccessControl.FileSystemAccessRule("{username}","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($rule); Set-Acl "{local_path}" $acl
""")

def setup_shares(config):
    create_all_shares(config); create_home_directories(config)
