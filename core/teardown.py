"""
core/teardown.py - remove the lab, touching ONLY what this tool owns.

A VM or switch is removed only if BOTH hold:
  * its name is defined in this lab's config (allowlist), and
  * its Hyper-V Notes field carries this lab's ownership tag.
Anything else with a matching name is reported and left alone.  Files are only
deleted from inside the project folder.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from config_loader import get_lab_root, get_unattend_dir, get_internal_switch
from core import ownership
from core.preflight import host_facts
from utils.powershell_runner import run_ps, run_ps_json
from utils.logger import get_logger

log = get_logger("teardown")


def build_plan(facts: dict | None = None) -> dict:
    """What a teardown would do, as data.  Read-only."""
    facts = facts if facts is not None else host_facts()
    present = {v["Name"]: v for v in facts["vms"]}
    switches = {s["Name"]: s for s in facts["switches"]}

    plan = {"vms": [], "switches": [], "skipped": [], "ghosts": []}
    for name in ownership.lab_vm_names():
        if name in present:
            if present[name].get("Owned"):
                plan["vms"].append(name)
            else:
                plan["skipped"].append(f"VM {name}: exists but is not owned by this lab - left alone")
        elif any(r["Name"] == name for r in facts["registered"]):
            plan["ghosts"].append(name)

    sw = get_internal_switch()
    if sw in switches:
        if switches[sw].get("Owned"):
            plan["switches"].append(sw)
        else:
            plan["skipped"].append(f"Switch {sw}: exists but is not owned by this lab - left alone")
    return plan


def print_plan(plan: dict) -> None:
    print("\n  Teardown plan (only objects tagged '%s' are removed):" % ownership.tag())
    for v in plan["vms"]:
        print(f"    - remove VM        {v}")
    for s in plan["switches"]:
        print(f"    - remove switch    {s}")
    print(f"    - delete folder    {get_lab_root()}  (VM disks, only inside the project)")
    print(f"    - delete generated {get_unattend_dir()}  (answer files)")
    print(f"    - clear            state/manifest.json and the build checkpoint")
    for line in plan["skipped"]:
        print(f"    ! {line}")
    for g in plan["ghosts"]:
        print(f"    ! {g}: broken VM record - run 'python main.py doctor' to clear it")
    if not (plan["vms"] or plan["switches"]):
        print("    (no lab VMs or switches present)")
    print()


def _remove_vm(name: str) -> None:
    ownership.assert_vm_allowed(name)
    rec = run_ps_json(f'Get-VM -Name "{name}" -ErrorAction SilentlyContinue | '
                      f'Select-Object Name, @{{N="Owned";E={{{ownership.ps_owned()}}}}}, '
                      f'@{{N="Disks";E={{@($_.HardDrives.Path)}}}}', timeout=60)
    if not rec:
        return
    if not rec.get("Owned"):
        raise ownership.OwnershipError(f"VM '{name}' lost its ownership tag; refusing to remove it.")
    disks = rec.get("Disks") or []
    disks = disks if isinstance(disks, list) else [disks]

    run_ps(f'$vm = Get-VM -Name "{name}"; if ($vm.State -ne "Off") {{ Stop-VM -Name "{name}" -TurnOff -Force }}; '
           f'Remove-VM -Name "{name}" -Force', timeout=180)
    ownership.forget("vm", name)
    log.info(f"[TEARDOWN] Removed VM {name}")

    lab_root = Path(get_lab_root()).resolve()
    for d in disks:
        p = Path(d).resolve()
        try:
            p.relative_to(lab_root)
        except ValueError:
            log.warning(f"[TEARDOWN] Not deleting disk outside the lab folder: {p}")
            continue
        if p.exists():
            p.unlink()
            log.info(f"[TEARDOWN]   deleted disk {p.name}")

    vm_dir = lab_root / name
    if vm_dir.exists():
        ownership.assert_inside_project(vm_dir)
        shutil.rmtree(vm_dir, ignore_errors=True)


def _remove_switch(name: str) -> None:
    ownership.assert_switch_allowed(name)
    run_ps(f'Remove-VMSwitch -Name "{name}" -Force', timeout=120)
    ownership.forget("switch", name)
    log.info(f"[TEARDOWN] Removed switch {name}")


def _clean_generated(skipped_any: bool) -> None:
    unattend = Path(get_unattend_dir())
    for name in ownership.lab_vm_names():
        d = unattend / name
        if d.exists():
            ownership.assert_inside_project(d)
            shutil.rmtree(d, ignore_errors=True)
    lab_root = Path(get_lab_root())
    if lab_root.exists() and not skipped_any:
        ownership.assert_inside_project(lab_root)
        if not any(lab_root.iterdir()):
            lab_root.rmdir()
    ownership.clear()
    from utils.checkpoint import reset_state
    reset_state()


def teardown(dry_run: bool = False, assume_yes: bool = False, input_fn=input) -> dict:
    plan = build_plan()
    print_plan(plan)
    if dry_run:
        print("  Dry run: nothing was changed.\n")
        return plan
    if not (plan["vms"] or plan["switches"]):
        _clean_generated(skipped_any=bool(plan["skipped"]))
        return plan
    if not assume_yes:
        answer = input_fn(f"  Type '{ownership.tag()}' to confirm: ").strip()
        if answer != ownership.tag():
            print("  Cancelled. Nothing was changed.\n")
            return plan
    for name in plan["vms"]:
        _remove_vm(name)
    for name in plan["switches"]:
        _remove_switch(name)
    _clean_generated(skipped_any=bool(plan["skipped"]))
    print("  Lab removed.\n")
    return plan


# ── Ghost VM records (registered in Hyper-V but their files are gone) ────────

def remove_ghost_records(assume_yes: bool = False, input_fn=input) -> list[str]:
    """
    Clear broken VM registrations whose names are in THIS lab's config.
    Only the registration is destroyed (DestroySystem); no disk is deleted.
    A VM is a ghost only if Get-VM cannot see it but the virtualization
    provider still lists it in the critical-health state (25).
    """
    facts = host_facts()
    visible = {v["Name"] for v in facts["vms"]}
    ghosts = [r["Name"] for r in facts["registered"]
              if r["Name"] in ownership.lab_vm_names() and r["Name"] not in visible and r.get("Health") == 25]
    if not ghosts:
        print("\n  No broken VM records for this lab.\n")
        return []
    print("\n  Broken VM records that will be cleared (registration only, no files deleted):")
    for g in ghosts:
        print(f"    - {g}")
    if not assume_yes and input_fn("  Type 'yes' to continue: ").strip().lower() != "yes":
        print("  Cancelled.\n")
        return []
    for g in ghosts:
        ownership.assert_vm_allowed(g)
        run_ps(f"""
$ns  = 'root\\virtualization\\v2'
$svc = Get-CimInstance -Namespace $ns -ClassName Msvm_VirtualSystemManagementService
$vm  = Get-CimInstance -Namespace $ns -ClassName Msvm_ComputerSystem -Filter "ElementName='{g}' AND Caption='Virtual Machine' AND HealthState=25"
if (-not $vm) {{ Write-Output "not a ghost: {g}"; exit }}
$r = Invoke-CimMethod -InputObject $svc -MethodName DestroySystem -Arguments @{{ AffectedSystem = $vm }}
if ($r.ReturnValue -eq 4096) {{
    do {{ Start-Sleep -Milliseconds 500; $job = Get-CimInstance -InputObject $r.Job }} while ($job.JobState -in 2,3,4)
    if ($job.JobState -ne 7) {{ throw "DestroySystem failed: $($job.ErrorDescription)" }}
}}
Write-Output "cleared: {g}"
""", timeout=180)
        log.info(f"[DOCTOR] Cleared broken VM record {g}")
    print()
    return ghosts
