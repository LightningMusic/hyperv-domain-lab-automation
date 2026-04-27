"""
core/validators.py
Pre-run and post-run validation checks.
"""
import shutil
from utils.powershell_runner import run_ps
from config_loader import get_admin_password

ADMIN_PASS = get_admin_password()

from typing import Optional

def _safe(r: Optional[str]) -> str:
    # If r is None, it defaults to an empty string before strip/lower
    return (r or "").strip().lower()


def _ps_in_vm(vm: str, cmd: str) -> str:
    try:
        return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{vm}" -Credential $cred -ErrorAction Stop `
    -ScriptBlock {{
$ErrorActionPreference = "Stop"
{cmd}
}}
""", return_output=True) or ""
    except Exception:
        return ""


class PreRunValidator:
    def __init__(self, required_gb: int = 200):
        self.required_gb = required_gb

    def check_disk_space(self, path: str) -> dict:
        total, used, free = shutil.disk_usage(path)
        free_gb = free / (1024 ** 3)
        return {
            "free_gb":     round(free_gb, 2),
            "required_gb": self.required_gb,
            "ok":          free_gb >= self.required_gb,
        }

    def validate_or_exit(self, path: str) -> dict:
        r = self.check_disk_space(path)
        if not r["ok"]:
            raise SystemExit(
                f"Not enough disk space. Free: {r['free_gb']} GB  Required: {r['required_gb']} GB"
            )
        return r


def vm_exists(vm_name: str) -> bool:
    try:
        r = run_ps(
            f'Get-VM -Name "{vm_name}" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name',
            return_output=True
        )
        return bool(r and vm_name.lower() in r.lower())
    except Exception:
        return False


def domain_exists(domain: str) -> bool:
    r = run_ps(
        f'Try {{(Get-ADDomain -Identity "{domain}").Name}} Catch {{""}}',
        return_output=True
    )
    return domain.lower() in _safe(r)


def dhcp_configured() -> bool:
    r = run_ps(
        'Try {Get-DhcpServerv4Scope | Select-Object -ExpandProperty ScopeId} Catch {""}',
        return_output=True
    )
    return bool(_safe(r))


def is_domain_joined(vm: str) -> bool:
    r = _ps_in_vm(vm, "(Get-WmiObject Win32_ComputerSystem).PartOfDomain")
    return "true" in _safe(r)


def gpo_applied(vm: str) -> bool:
    r = _ps_in_vm(vm, "gpresult /r /scope computer")
    return "acme baseline policy" in _safe(r)


def ou_exists(ou_dn: str) -> bool:
    r = run_ps(
        f'Try{{Get-ADOrganizationalUnit -Identity "{ou_dn}"}}Catch{{""}}',
        return_output=True
    )
    return bool(_safe(r))


def user_exists(username: str) -> bool:
    r = run_ps(
        f'Try{{Get-ADUser -Identity "{username}"}}Catch{{""}}',
        return_output=True
    )
    return username.lower() in _safe(r)
