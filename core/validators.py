from utils.powershell_runner import run_ps

import shutil

class PreRunValidator:

    def __init__(self, required_gb=150):
        self.required_gb = required_gb

    def check_disk_space(self, path):
        total, used, free = shutil.disk_usage(path)

        free_gb = free / (1024 ** 3)

        return {
            "free_gb": round(free_gb, 2),
            "required_gb": self.required_gb,
            "ok": free_gb >= self.required_gb
        }

    def validate_or_exit(self, path):
        result = self.check_disk_space(path)

        if not result["ok"]:
            raise Exception(
                f"Not enough disk space. "
                f"Free: {result['free_gb']} GB, "
                f"Required: {result['required_gb']} GB"
            )

        return result

def safe_output(result):
    return (result or "").lower()


# ------------------------------------------------
# VM
# ------------------------------------------------

def vm_exists(vm_name):
    result = run_ps(f'Get-VM -Name "{vm_name}"', return_output=True)
    output = safe_output(result)
    return vm_name.lower() in output


# ------------------------------------------------
# DOMAIN
# ------------------------------------------------

def domain_exists(domain):
    result = run_ps(
        f'Try {{ Get-ADDomain -Identity "{domain}" }} Catch {{ "" }}',
        return_output=True
    )
    output = safe_output(result)
    return domain.lower() in output


# ------------------------------------------------
# DHCP
# ------------------------------------------------

def dhcp_configured():
    result = run_ps(
        "Try { Get-DhcpServerv4Scope } Catch { '' }",
        return_output=True
    )
    output = safe_output(result)
    return "scopeid" in output


# ------------------------------------------------
# DOMAIN JOIN
# ------------------------------------------------

def is_domain_joined(vm):
    ps = f"""
Invoke-Command -VMName "{vm}" -ScriptBlock {{
    (Get-WmiObject Win32_ComputerSystem).PartOfDomain
}} -ErrorAction SilentlyContinue
"""
    result = run_ps(ps, return_output=True)
    output = safe_output(result)
    return "true" in output


# ------------------------------------------------
# GPO
# ------------------------------------------------

def gpo_applied(vm):
    ps = f"""
Invoke-Command -VMName "{vm}" -ScriptBlock {{
    gpresult /r
}} -ErrorAction SilentlyContinue
"""
    result = run_ps(ps, return_output=True)
    output = safe_output(result)
    return "applied group policy objects" in output