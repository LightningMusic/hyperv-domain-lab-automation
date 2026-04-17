from utils.powershell_runner import run_ps

def _parse_perm(s):
    identity,access=s.split(":"); return identity.strip(),access.strip()

def create_share(share_config):
    name=share_config["name"]; path=share_config["path"]
    identity,access=_parse_perm(share_config["share_permissions"])
    print(f"[SHARE] {name} at {path}")
    run_ps(f"""
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
        local_path=home["path"].replace("\\\\AcmePDC01\\Users$","E:\\Users$")
        print(f"[HOME] {username}")
        run_ps(f"""
if(-not(Test-Path "{local_path}")){{New-Item -Path "{local_path}" -ItemType Directory -Force}}
$acl=Get-Acl "{local_path}"
$rule=New-Object System.Security.AccessControl.FileSystemAccessRule("{username}","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($rule); Set-Acl "{local_path}" $acl
""")

def setup_shares(config):
    create_all_shares(config); create_home_directories(config)