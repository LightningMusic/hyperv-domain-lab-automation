import time
from utils.powershell_runner import run_ps
from config_loader import get_domain_join, get_domain_config, get_dc_name, get_workstation_name, get_admin_password

DC_VM          = get_dc_name()
WORKSTATION_VM = get_workstation_name()
ADMIN_PASS     = get_admin_password()

def _run_on_vm(vm_name, ps):
    return run_ps(f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator", $sp)
Invoke-Command -VMName "{vm_name}" -Credential $cred -ScriptBlock {{ {ps} }}
""", return_output=True)

def is_domain_joined(vm_name):
    r=_run_on_vm(vm_name,"(Get-WmiObject Win32_ComputerSystem).PartOfDomain")
    return bool(r) and r.strip().lower()=="true"

def wait_for_dc(domain_name, timeout=600):
    print("[JOIN] Waiting for DC...")
    start=time.time()
    while time.time()-start<timeout:
        try:
            r=_run_on_vm(WORKSTATION_VM, f'Resolve-DnsName "{domain_name}" -EA Stop')
            if r: print("[JOIN] Domain reachable."); return True
        except Exception: pass
        print("[JOIN] Waiting 15s...")
        time.sleep(15)
    raise TimeoutError("Domain controller not reachable.")

def join_machine(vm_name, domain_name):
    print(f"[JOIN] Joining {vm_name} to {domain_name}")
    _run_on_vm(vm_name, f"""
$sp   = ConvertTo-SecureString "{ADMIN_PASS}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ("Administrator@{domain_name}", $sp)
Add-Computer -DomainName "{domain_name}" -Credential $cred -Force -EA Stop
Restart-Computer -Force
""")

def wait_for_vm(vm_name, timeout=600):
    print(f"[JOIN] Waiting for {vm_name} reboot...")
    start=time.time()
    while time.time()-start<timeout:
        try:
            r=_run_on_vm(vm_name,"hostname")
            if r: print(f"[JOIN] {vm_name} online."); return True
        except Exception: pass
        print(f"[JOIN] Waiting for {vm_name}...")
        time.sleep(15)
    raise TimeoutError(f"{vm_name} did not come back online.")

def move_to_ou(vm_name, target_ou, domain_name):
    ou_parts=target_ou.split("/")
    ou_dn=",".join([f"OU={p}" for p in reversed(ou_parts)])
    domain_dn=",".join([f"DC={x}" for x in domain_name.split(".")])
    full_dn=f"{ou_dn},{domain_dn}"
    print(f"[JOIN] Moving {vm_name} to {full_dn}")
    _run_on_vm(DC_VM, f"""
Import-Module ActiveDirectory
$c=Get-ADComputer "{vm_name}"
Move-ADObject -Identity $c.DistinguishedName -TargetPath "{full_dn}"
""")

def force_gpupdate(vm_name):
    _run_on_vm(vm_name, "gpupdate /force")

def join_workstations_to_domain():
    join_cfg    = get_domain_join()
    domain_cfg  = get_domain_config()
    domain_name = domain_cfg["name"]
    workstations= join_cfg.get("workstations", [])
    target_ou   = join_cfg.get("target_ou", "CorporateOffice/Computers")

    print("\n[JOIN] Starting domain join process...\n")
    for vm in workstations:
        if is_domain_joined(vm):
            print(f"[JOIN] {vm} already joined. Skipping."); continue
        wait_for_dc(domain_name)
        join_machine(vm, domain_name)
        wait_for_vm(vm)
        move_to_ou(vm, target_ou, domain_name)
        force_gpupdate(vm)
    print("\n[JOIN] Domain join COMPLETE.\n")