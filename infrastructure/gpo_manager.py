from utils.powershell_runner import run_ps
from config_loader import get_gpo_config, get_dc_name, get_domain_config, get_admin_password

DC_VM      = get_dc_name()
ADMIN_PASS = get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{
Import-Module GroupPolicy
{ps}
}}
""", return_output=True)

def _domain_dn():
    domain=get_domain_config()["name"]
    return ",".join([f"DC={p}" for p in domain.split(".")])

def ensure_gpo(name):
    print(f"[GPO] Ensuring GPO: {name}")
    _run_on_dc(f'$g=Get-GPO -Name "{name}" -EA SilentlyContinue; if(-not $g){{New-GPO -Name "{name}"}}')

def link_gpo(name):
    target=_domain_dn()
    print(f"[GPO] Linking {name} -> {target}")
    _run_on_dc(f'New-GPLink -Name "{name}" -Target "{target}" -Enforced:$false -EA SilentlyContinue')

def configure_password_policy(cfg):
    p=cfg.get("password_policy",{})
    min_len=p.get("minimum_length",10); max_age=p.get("maximum_age_days",180)
    print("[GPO] Password policy")
    _run_on_dc(f"net accounts /minpwlen:{min_len}; net accounts /maxpwage:{max_age}")

def configure_lockout_policy(cfg):
    p=cfg.get("account_lockout",{})
    thr=p.get("threshold",10); dur=p.get("duration_minutes",40); rst=p.get("reset_minutes",30)
    print("[GPO] Lockout policy")
    _run_on_dc(f"net accounts /lockoutthreshold:{thr}; net accounts /lockoutduration:{dur}; net accounts /lockoutwindow:{rst}")

def rename_accounts(cfg):
    r=cfg.get("rename_accounts",{}); admin=r.get("administrator"); guest=r.get("guest")
    print("[GPO] Renaming built-in accounts")
    if admin: _run_on_dc(f'Rename-LocalUser -Name "Administrator" -NewName "{admin}" -EA SilentlyContinue')
    if guest: _run_on_dc(f'Rename-LocalUser -Name "Guest" -NewName "{guest}" -EA SilentlyContinue')

def configure_logon(cfg):
    l=cfg.get("interactive_logon",{}); title=l.get("banner_title",""); msg=l.get("banner_message",""); hide=1 if l.get("hide_last_user",True) else 0
    print("[GPO] Logon policies")
    _run_on_dc(f"""
$reg="HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System"
Set-ItemProperty -Path $reg -Name LegalNoticeCaption -Value "{title}"
Set-ItemProperty -Path $reg -Name LegalNoticeText    -Value "{msg}"
Set-ItemProperty -Path $reg -Name DontDisplayLastUserName -Value {hide}
""")

def configure_inactivity(cfg):
    t=cfg.get("inactivity_timeout_seconds",600)
    _run_on_dc(f'Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" -Name InactivityTimeoutSecs -Value {t}')

def configure_wallpaper(cfg):
    w=cfg.get("desktop_background",{}); path=w.get("path")
    if not path: return
    _run_on_dc(f'Set-ItemProperty -Path "HKCU:\\Control Panel\\Desktop" -Name Wallpaper -Value "{path}"')

def configure_drive_mappings(cfg):
    for m in cfg.get("drive_mappings",[]):
        letter=m["drive_letter"]; path=m["path"]
        _run_on_dc(f'New-PSDrive -Name "{letter}" -PSProvider FileSystem -Root "{path}" -Persist -EA SilentlyContinue')

def configure_gpo():
    cfg=get_gpo_config(); gpo_name="ACME Baseline Policy"
    print("\n[GPO] Starting GPO configuration...\n")
    ensure_gpo(gpo_name); link_gpo(gpo_name)
    domain_sec=cfg.get("domain_security",{})
    configure_password_policy(domain_sec); configure_lockout_policy(domain_sec)
    rename_accounts(cfg); configure_logon(cfg); configure_inactivity(cfg)
    configure_wallpaper(cfg); configure_drive_mappings(cfg)
    print("\n[GPO] GPO configuration COMPLETE.\n")