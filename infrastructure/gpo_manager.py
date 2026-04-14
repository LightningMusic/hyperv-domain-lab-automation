from utils.powershell_runner import run_ps
from config_loader import get_gpo_config


DC_VM = "ACME-DC01"
DOMAIN = "ad.acme.edu"


# ------------------------------------------------
# Run inside DC
# ------------------------------------------------

def run_on_dc(ps_script):
    wrapped = f"""
Invoke-Command -VMName "{DC_VM}" -ScriptBlock {{
Import-Module GroupPolicy
{ps_script}
}}
"""
    return run_ps(wrapped, return_output=True)


# ------------------------------------------------
# Ensure GPO exists
# ------------------------------------------------

def ensure_gpo(name):
    print(f"[GPO] Ensuring GPO exists: {name}")

    ps = f"""
$gpo = Get-GPO -Name "{name}" -ErrorAction SilentlyContinue

if (-not $gpo) {{
    New-GPO -Name "{name}"
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Link GPO
# ------------------------------------------------

def link_gpo(name, target="DC=ad,DC=acme,DC=edu"):
    print(f"[GPO] Linking {name} to {target}")

    ps = f"""
New-GPLink `
    -Name "{name}" `
    -Target "{target}" `
    -Enforced:$false `
    -ErrorAction SilentlyContinue
"""
    run_on_dc(ps)


# ------------------------------------------------
# Password Policy
# ------------------------------------------------

def configure_password_policy(config):
    policy = config.get("password_policy", {})

    min_len = policy.get("minimum_length", 10)
    max_age = policy.get("maximum_age_days", 180)

    print("[GPO] Configuring password policy")

    ps = f"""
net accounts /minpwlen:{min_len}
net accounts /maxpwage:{max_age}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Account Lockout Policy
# ------------------------------------------------

def configure_lockout_policy(config):
    policy = config.get("account_lockout", {})

    threshold = policy.get("threshold", 10)
    duration = policy.get("duration_minutes", 40)
    reset = policy.get("reset_minutes", 30)

    print("[GPO] Configuring account lockout")

    ps = f"""
net accounts /lockoutthreshold:{threshold}
net accounts /lockoutduration:{duration}
net accounts /lockoutwindow:{reset}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Rename Accounts
# ------------------------------------------------

def rename_accounts(config):
    rename = config.get("rename_accounts", {})

    admin = rename.get("administrator")
    guest = rename.get("guest")

    print("[GPO] Renaming built-in accounts")

    ps = f"""
if ("{admin}") {{
    Rename-LocalUser -Name "Administrator" -NewName "{admin}" -ErrorAction SilentlyContinue
}}

if ("{guest}") {{
    Rename-LocalUser -Name "Guest" -NewName "{guest}" -ErrorAction SilentlyContinue
}}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Interactive Logon Settings
# ------------------------------------------------

def configure_logon(config):
    logon = config.get("interactive_logon", {})

    title = logon.get("banner_title", "")
    message = logon.get("banner_message", "")
    hide_user = logon.get("hide_last_user", True)

    print("[GPO] Configuring logon policies")

    ps = f"""
Set-ItemProperty `
    -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" `
    -Name "LegalNoticeCaption" `
    -Value "{title}"

Set-ItemProperty `
    -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" `
    -Name "LegalNoticeText" `
    -Value "{message}"

Set-ItemProperty `
    -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" `
    -Name "DontDisplayLastUserName" `
    -Value {1 if hide_user else 0}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Inactivity Timeout
# ------------------------------------------------

def configure_inactivity(config):
    timeout = config.get("inactivity_timeout_seconds", 600)

    print("[GPO] Setting inactivity timeout")

    ps = f"""
Set-ItemProperty `
    -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" `
    -Name "InactivityTimeoutSecs" `
    -Value {timeout}
"""
    run_on_dc(ps)


# ------------------------------------------------
# Desktop Background
# ------------------------------------------------

def configure_wallpaper(config):
    wallpaper = config.get("desktop_background", {})

    path = wallpaper.get("path")
    style = wallpaper.get("style", "Fill")

    if not path:
        return

    print("[GPO] Setting desktop background")

    ps = f"""
Set-ItemProperty `
    -Path "HKCU:\\Control Panel\\Desktop" `
    -Name "Wallpaper" `
    -Value "{path}"
"""
    run_on_dc(ps)


# ------------------------------------------------
# Drive Mappings (basic)
# ------------------------------------------------

def configure_drive_mappings(config):
    mappings = config.get("drive_mappings", [])

    if not mappings:
        return

    print("[GPO] Configuring drive mappings")

    for m in mappings:
        letter = m["drive_letter"]
        path = m["path"]

        ps = f"""
New-PSDrive `
    -Name "{letter}" `
    -PSProvider FileSystem `
    -Root "{path}" `
    -Persist `
    -ErrorAction SilentlyContinue
"""
        run_on_dc(ps)


# ------------------------------------------------
# Main Entry
# ------------------------------------------------

def configure_gpo():
    config = get_gpo_config()

    print("\n[GPO] Starting GPO configuration...\n")

    gpo_name = "ACME Baseline Policy"

    ensure_gpo(gpo_name)
    link_gpo(gpo_name)

    # Domain-level policies
    domain_sec = config.get("domain_security", {})
    configure_password_policy(domain_sec)
    configure_lockout_policy(domain_sec)

    # System policies
    rename_accounts(config)
    configure_logon(config)
    configure_inactivity(config)
    configure_wallpaper(config)
    configure_drive_mappings(config)

    print("\n[GPO] GPO configuration COMPLETE.\n")