import argparse
import sys

from utils.powershell_runner import run_ps_script, require_admin
from utils.powershell_runner import run_ps
from utils.checkpoint import run_step, reset_state

from core.hyperv_manager import (
    verify_hyperv_installed,
    verify_iso_files,
    create_lab_directory,
    generate_unattend_files,
    create_external_switch,
    create_router_vm,
    create_domain_controller_vm,
    create_workstation_vm,
    configure_router_network,
    start_all_vms,
    wait_for_all_installs,
    configure_full_environment,
)

from core.network_config import configure_networking
from config_loader import load_config

from domain.ad_installer import install_active_directory
from domain.dhcp_config import configure_dhcp
from domain.ou_manager import create_organizational_units
from domain.user_manager import create_users_and_groups
from core.orchestrator import Orchestrator, Step
from core.progress_tracker import ProgressTracker
from core.validators import *
from core.hyperv_manager import join_workstation_to_domain

LAB_DESTROY_SCRIPT = "destroy_lab.ps1"


# ------------------------------------------------
# Destroy
# ------------------------------------------------

def destroy_lab():
    print("\nDestroying lab environment...\n")
    run_ps_script(LAB_DESTROY_SCRIPT)
    reset_state()


# ------------------------------------------------
# Build (Orchestrator Driven)
# ------------------------------------------------

tracker = ProgressTracker()
orch = Orchestrator()


# -------------------------
# Define Steps (no duplicates)
# -------------------------

orch.add_step(Step(
    "Verify Hyper-V",
    action=verify_hyperv_installed,
    validate=lambda: True
))

orch.add_step(Step(
    "Verify ISOs",
    action=verify_iso_files,
    validate=lambda: True
))

orch.add_step(Step(
    "Create Lab Directory",
    action=create_lab_directory,
    validate=lambda: True
))

orch.add_step(Step(
    "Generate Unattend Files",
    action=generate_unattend_files,
    validate=lambda: True
))

orch.add_step(Step(
    "Create Switch",
    action=create_external_switch,
    validate=lambda: True
))

orch.add_step(Step(
    "Create Router VM",
    action=create_router_vm,
    validate=lambda: vm_exists("ACME-Router")
))

orch.add_step(Step(
    "Create DC VM",
    action=create_domain_controller_vm,
    validate=lambda: vm_exists("ACME-DC01")
))

orch.add_step(Step(
    "Create Workstation VM",
    action=create_workstation_vm,
    validate=lambda: vm_exists("ACME-WKS01")
))

orch.add_step(Step(
    "Configure Router Network",
    action=configure_router_network,
    validate=lambda: True
))

orch.add_step(Step(
    "Start VMs",
    action=start_all_vms,
    validate=lambda: True
))

orch.add_step(Step(
    "Wait for OS Install",
    action=wait_for_all_installs,
    validate=lambda: True
))

orch.add_step(Step(
    "Install Active Directory",
    action=install_active_directory,
    validate=lambda: domain_exists("ad.acme.edu")
))

orch.add_step(Step(
    "Configure DHCP",
    action=configure_dhcp,
    validate=dhcp_configured
))

orch.add_step(Step(
    "Create Organizational Units",
    action=create_organizational_units,
    validate=lambda: True
))

orch.add_step(Step(
    "Create Users and Groups",
    action=create_users_and_groups,
    validate=lambda: True
))

orch.add_step(Step(
    "Join Domain",
    action=join_workstation_to_domain,
    validate=lambda: is_domain_joined("ACME-WKS01")
))

orch.add_step(Step(
    "Verify GPO",
    action=lambda: None,
    validate=lambda: gpo_applied("ACME-WKS01")
))


def build_lab():
    print("\n🚀 Starting FULL Automated Deployment\n")
    orch.run(tracker=tracker)


# ------------------------------------------------
# Rebuild
# ------------------------------------------------

def rebuild_lab():
    print("\nRebuilding lab...\n")
    destroy_lab()
    build_lab()


# ------------------------------------------------
# Status
# ------------------------------------------------

def show_status():
    print("\n[STATUS] ACME Lab VMs\n")

    ps = """
$vms = Get-VM | Where-Object {$_.Name -like "ACME-*"}

if (-not $vms) {
    Write-Output "No ACME VMs found."
} else {
    $vms | Select Name, State, CPUUsage, MemoryAssigned | Format-Table -AutoSize
}
"""

    run_ps(ps)


# ------------------------------------------------
# CLI
# ------------------------------------------------

def main():
    require_admin()

    parser = argparse.ArgumentParser(
        description="ACME Hyper-V Lab Automation Tool"
    )

    parser.add_argument(
        "command",
        choices=["build", "destroy", "rebuild", "status"],
    )

    args = parser.parse_args()

    if args.command == "build":
        build_lab()

    elif args.command == "destroy":
        destroy_lab()

    elif args.command == "rebuild":
        rebuild_lab()

    elif args.command == "status":
        show_status()


if __name__ == "__main__":
    main()