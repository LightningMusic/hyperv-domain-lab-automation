"""
core/preflight.py - read-only checks that run BEFORE anything is created.

Nothing here changes the host.  Every check reports PASS / WARN / FAIL; any
FAIL aborts the build.  `python main.py preflight` runs the same checks on demand.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
from dataclasses import dataclass

from config_loader import (
    PROJECT_ROOT, get_vms, get_lab_root, get_server_iso, get_win11_iso,
    get_internal_switch, get_uplink_switch_id, get_uplink_switch_name,
    get_network_config, get_preflight_config, is_within_project,
)
from core import ownership
from utils.powershell_runner import run_ps_json
from utils.logger import get_logger

log = get_logger("preflight")


class PreflightError(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    status: str      # PASS | WARN | FAIL
    detail: str = ""


_HOST_FACTS_PS = r"""
$vms = @(Get-VM -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{ Name = $_.Name; State = "$($_.State)"; Owned = __OWNED__ } })
$registered = @(Get-CimInstance -Namespace root\virtualization\v2 -ClassName Msvm_ComputerSystem `
    -Filter "Caption='Virtual Machine'" -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{ Name = $_.ElementName; Health = [int]$_.HealthState } })
$switches = @(Get-VMSwitch -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{ Name = $_.Name; Id = "$($_.Id)"; Type = "$($_.SwitchType)"; Owned = __OWNED__ } })
$ips  = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    ForEach-Object { "$($_.IPAddress)/$($_.PrefixLength)" })
$nats = @(Get-NetNat -ErrorAction SilentlyContinue | ForEach-Object { $_.InternalIPInterfaceAddressPrefix })
$os   = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{
    vmms       = "$((Get-Service vmms -ErrorAction SilentlyContinue).Status)"
    freeMemGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    vms        = $vms
    registered = $registered
    switches   = $switches
    ips        = $ips
    nats       = $nats
}
"""


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def host_facts() -> dict:
    """
    One read-only query for everything the checks (and teardown) need.
    Privacy: the Notes of VMs/switches are NOT read back; only an 'Owned'
    yes/no computed on the host, so other labs' notes never enter our logs.
    """
    facts = run_ps_json(_HOST_FACTS_PS.replace("__OWNED__", ownership.ps_owned()), timeout=120) or {}
    for key in ("vms", "registered", "switches", "ips", "nats"):
        facts[key] = _as_list(facts.get(key))
    return facts


# ── Individual checks (pure functions of facts + config: unit-testable) ──────

def check_hyperv(facts) -> Check:
    if facts.get("vmms") == "Running":
        return Check("Hyper-V (vmms) running", "PASS")
    return Check("Hyper-V (vmms) running", "FAIL", f"vmms status is '{facts.get('vmms') or 'not installed'}'")


def check_media() -> list[Check]:
    out = []
    for label, iso in (("Server ISO", get_server_iso()), ("Windows 11 ISO", get_win11_iso())):
        if os.path.isfile(iso):
            out.append(Check(label, "PASS", os.path.relpath(iso, PROJECT_ROOT)))
        else:
            out.append(Check(label, "FAIL", f"missing: {iso} (see install_media/README.md)"))
    return out


def check_disk(min_free_gb: int) -> Check:
    root = get_lab_root()
    if not is_within_project(root):
        return Check("Lab root inside project", "FAIL", root)
    free_gb = shutil.disk_usage(PROJECT_ROOT).free / 1024 ** 3
    if free_gb < min_free_gb:
        return Check("Free disk space", "FAIL", f"{free_gb:.0f} GB free, need {min_free_gb} GB")
    return Check("Free disk space", "PASS", f"{free_gb:.0f} GB free (need {min_free_gb} GB)")


def check_ram(facts, vm_names: list[str], headroom_gb: int) -> Check:
    need = sum(int(v.get("ram_gb", 2)) for v in get_vms() if v["name"] in vm_names)
    free = float(facts.get("freeMemGB") or 0)
    if free - need < headroom_gb:
        return Check("Free RAM", "FAIL", f"{free:.1f} GB free; lab needs {need} GB + {headroom_gb} GB headroom")
    return Check("Free RAM", "PASS", f"{free:.1f} GB free; lab needs {need} GB")


def check_vm_specs() -> list[Check]:
    """Catch configs that cannot install (before spending an hour finding out)."""
    out = []
    for v in get_vms():
        role, name = v.get("role"), v["name"]
        if role == "workstation":    # Windows 11 hard requirements
            bad = []
            if int(v.get("cpu", 1)) < 2:      bad.append("needs >= 2 vCPU")
            if int(v.get("ram_gb", 0)) < 4:   bad.append("needs >= 4 GB RAM")
            if int(v.get("disk_gb", 0)) < 64: bad.append("needs >= 64 GB disk")
            out.append(Check(f"{name} meets Windows 11 minimums", "FAIL" if bad else "PASS", "; ".join(bad)))
        elif role in ("router", "domain_controller", "storage"):
            if int(v.get("disk_gb", 0)) < 32:
                out.append(Check(f"{name} meets Server 2022 minimums", "FAIL", "needs >= 32 GB disk"))
    return out


def check_vm_collisions(facts, vm_names: list[str]) -> list[Check]:
    out = []
    present = {v["Name"]: v for v in facts["vms"]}
    for name in vm_names:
        if name in present:
            if present[name].get("Owned"):
                out.append(Check(f"VM {name}", "PASS", f"exists, owned by this lab ({present[name]['State']}); will be reused"))
            else:
                out.append(Check(f"VM {name}", "FAIL", "a VM with this name exists and is NOT owned by this lab; it will not be touched"))
        elif any(r["Name"] == name for r in facts["registered"]):
            out.append(Check(f"VM {name}", "FAIL", "a broken (ghost) VM record with this name is registered; run 'python main.py doctor'"))
        else:
            out.append(Check(f"VM {name}", "PASS", "free to create"))
    return out


def check_switches(facts) -> list[Check]:
    out = []
    name = get_internal_switch()
    sw = next((s for s in facts["switches"] if s["Name"] == name), None)
    if sw is None:
        out.append(Check(f"Switch {name}", "PASS", "free to create (Private)"))
    elif not sw.get("Owned"):
        out.append(Check(f"Switch {name}", "FAIL", "exists and is NOT owned by this lab; it will not be touched"))
    elif sw.get("Type") != "Private":
        out.append(Check(f"Switch {name}", "FAIL", f"exists as {sw.get('Type')}; must be Private (run 'destroy' first)"))
    else:
        out.append(Check(f"Switch {name}", "PASS", "exists, Private, owned by this lab"))

    uid = get_uplink_switch_id().lower()
    if any(s["Id"].lower() == uid for s in facts["switches"]):
        out.append(Check(f"Uplink switch ({get_uplink_switch_name()})", "PASS", "present (router NIC will attach here)"))
    else:
        out.append(Check(f"Uplink switch ({get_uplink_switch_name()})", "FAIL",
                         f"switch {uid} not found; the router would have no internet"))
    return out


def check_subnet_overlap(facts) -> Check:
    subnet = ipaddress.ip_network(get_network_config().get("subnet", "192.168.4.0/24"), strict=False)
    clashes = []
    for cidr in facts["ips"]:
        try:
            if ipaddress.ip_interface(cidr).ip in subnet:
                clashes.append(f"host address {cidr}")
        except ValueError:
            pass
    for cidr in facts["nats"]:
        try:
            if ipaddress.ip_network(cidr, strict=False).overlaps(subnet):
                clashes.append(f"NAT {cidr}")
        except ValueError:
            pass
    if clashes:
        return Check(f"Lab subnet {subnet} free on host", "FAIL", "; ".join(clashes))
    return Check(f"Lab subnet {subnet} free on host", "PASS")


# ── Runner ───────────────────────────────────────────────────────────────────

def run_checks(facts: dict | None = None, vm_names: list[str] | None = None,
               ram_headroom_gb: int | None = None) -> list[Check]:
    from core.hyperv_manager import CORE_VMS
    facts = facts if facts is not None else host_facts()
    vm_names = list(vm_names or CORE_VMS)
    cfg = get_preflight_config()
    headroom = cfg["ram_headroom_gb"] if ram_headroom_gb is None else ram_headroom_gb
    checks = [check_hyperv(facts)]
    checks += check_media()
    checks += [check_disk(cfg["min_free_gb"]), check_ram(facts, vm_names, headroom)]
    checks += check_vm_specs()
    checks += check_vm_collisions(facts, vm_names)
    checks += check_switches(facts)
    checks.append(check_subnet_overlap(facts))
    return checks


def print_report(checks: list[Check]) -> None:
    icon = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}
    print()
    for c in checks:
        print(f"  [{icon[c.status]}] {c.name}" + (f"  -  {c.detail}" if c.detail else ""))
    fails = sum(c.status == "FAIL" for c in checks)
    warns = sum(c.status == "WARN" for c in checks)
    print(f"\n  {len(checks)} checks: {len(checks) - fails - warns} passed, {warns} warnings, {fails} failed\n")


def run_preflight(raise_on_fail: bool = True, vm_names: list[str] | None = None,
                  ram_headroom_gb: int | None = None) -> list[Check]:
    checks = run_checks(vm_names=vm_names, ram_headroom_gb=ram_headroom_gb)
    print_report(checks)
    if raise_on_fail and any(c.status == "FAIL" for c in checks):
        raise PreflightError("Preflight failed; nothing was changed. Fix the FAIL items above and retry.")
    return checks
