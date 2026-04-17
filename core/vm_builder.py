"""core/vm_builder.py — builds all VMs from config."""
import time
from config_loader import load_config, get_lab_root, get_admin_password
from core.hyperv_manager import create_vm, start_vm, wait_for_install
from utils.powershell_runner import run_ps

def build_all():
    config = load_config()
    for vm in config.get("virtual_machines", []):
        if vm.get("role") == "web":
            continue  # Ubuntu handled by linux_manager
        create_vm(vm)
        start_vm(vm["name"])

def wait_for_all():
    config = load_config()
    for vm in config.get("virtual_machines", []):
        if vm.get("role") not in ("web",):
            wait_for_install(vm["name"])