import time
from utils.powershell_runner import run_ps
from config_loader import get_domain_config, get_dc_name, get_admin_password
from utils.logger import get_logger

log       = get_logger("ad_installer")
DC_VM     = get_dc_name()
ADMIN_PASS= get_admin_password()

def _run_on_dc(ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{DC_VM}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def is_ad_installed():
    r = _run_on_dc("$f=Get-WindowsFeature AD-Domain-Services;if($f.Installed){'True'}else{'False'}")
    return bool(r) and r.strip().lower()=="true"

def wait_for_dc_ready(timeout=600):
    log.info("[AD] Waiting for DC...")
    start=time.time()
    while time.time()-start<timeout:
        try:
            r=_run_on_dc("hostname")
            if r and r.strip(): log.info(f"[AD] DC online: {r.strip()}"); return True
        except Exception: pass
        time.sleep(15)
    raise TimeoutError("DC did not come back online.")

def verify_ad():
    r=_run_on_dc("Import-Module ActiveDirectory;(Get-ADDomain).Name")
    if not r or not r.strip(): raise RuntimeError("AD verification failed.")
    log.info(f"[AD] Domain confirmed: {r.strip()}")

def install_active_directory():
    cfg=get_domain_config()
    domain,netbios,safepass=cfg["name"],cfg["netbios"],cfg["safe_mode_password"]
    log.info(f"\n[AD] Installing Active Directory: {domain}\n")
    if is_ad_installed(): log.info("[AD] Already installed."); return
    _run_on_dc("Install-WindowsFeature AD-Domain-Services -IncludeManagementTools")
    _run_on_dc(f"""
Import-Module ADDSDeployment
$sp=ConvertTo-SecureString "{safepass}" -AsPlainText -Force
Install-ADDSForest -DomainName "{domain}" -DomainNetbiosName "{netbios}" -SafeModeAdministratorPassword $sp -InstallDNS -Force -NoRebootOnCompletion:$false
""")
    wait_for_dc_ready(); verify_ad()
    log.info("\n[AD] Active Directory COMPLETE.\n")