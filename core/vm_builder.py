import os
import time

from utils.powershell_runner import run_ps
from config_loader import load_config


CONFIG = load_config()
LAB_ROOT = CONFIG["paths"]["lab_root"]


def create_vm(vm: dict):
    name = vm["name"]
    cpu = vm.get("cpu", 1)
    ram = vm.get("ram_gb", 2)
    disk = vm.get("disk_gb", 60)
    switch = vm.get("network", "Default Switch")

    path = os.path.join(LAB_ROOT, name)
    vhd = os.path.join(path, f"{name}.vhdx")

    os.makedirs(path, exist_ok=True)

    print(f"[VM] {name}")

    run_ps(f"""
if (-not (Get-VM -Name "{name}" -ErrorAction SilentlyContinue)) {{

    New-VHD -Path "{vhd}" -SizeBytes {disk}GB -Dynamic

    New-VM `
        -Name "{name}" `
        -MemoryStartupBytes {ram}GB `
        -Generation 2 `
        -VHDPath "{vhd}" `
        -Path "{path}" `
        -SwitchName "{switch}"

    Set-VMProcessor -VMName "{name}" -Count {cpu}
}}
""")


def start_vm(name: str):
    run_ps(f'Start-VM -Name "{name}"')


def wait_for_vm(name: str, timeout=600):
    start = time.time()

    while time.time() - start < timeout:
        state = run_ps(f'(Get-VM -Name "{name}").State', return_output=True)

        if state and "Running" in state:
            print(f"[OK] {name}")
            return

        time.sleep(10)

    raise TimeoutError(name)


def build_all():
    for vm in CONFIG["virtual_machines"]:
        create_vm(vm)
        start_vm(vm["name"])
        wait_for_vm(vm["name"])