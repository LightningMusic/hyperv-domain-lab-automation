from utils.powershell_runner import run_ps
from config_loader import load_config
import os


LAB_ROOT = r"C:\CVNP-Python\Python Projects\Lab Deployment\LabVMs"


# ------------------------------------------------
# Helper: Create VM via PowerShell
# ------------------------------------------------

def create_vm(vm):
    name = vm["name"]
    cpu = vm.get("cpu", 1)
    ram_gb = vm.get("ram_gb", 2)
    disk_gb = vm.get("disk_gb", 60)
    switch = vm.get("network", "Default Switch")
    generation = vm.get("generation", 2)

    vm_path = os.path.join(LAB_ROOT, name)
    vhd_path = os.path.join(vm_path, f"{name}.vhdx")

    os.makedirs(vm_path, exist_ok=True)

    print(f"\n[VM] Creating {name}...")

    ps = f"""
$vmName = "{name}"
$vmPath = "{vm_path}"
$vhdPath = "{vhd_path}"

# Skip if VM exists
if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) {{
    Write-Output "[VM] {name} already exists. Skipping creation."
    return
}}

# Create disk
New-VHD `
    -Path $vhdPath `
    -SizeBytes {disk_gb}GB `
    -Dynamic

# Create VM
New-VM `
    -Name $vmName `
    -MemoryStartupBytes {ram_gb}GB `
    -Generation {generation} `
    -VHDPath $vhdPath `
    -Path $vmPath `
    -SwitchName "{switch}"

# CPU config
Set-VMProcessor `
    -VMName $vmName `
    -Count {cpu}

# Enable integration services (safe defaults)
Enable-VMIntegrationService -VMName $vmName -Name "Guest Service Interface" -ErrorAction SilentlyContinue
"""

    run_ps(ps)

    # Handle additional disks
    add_additional_disks(vm, vm_path)

    print(f"[VM] {name} created successfully.")


# ------------------------------------------------
# Additional Disks
# ------------------------------------------------

def add_additional_disks(vm, vm_path):
    disks = vm.get("additional_disks_gb", [])

    if not disks:
        return

    name = vm["name"]

    print(f"[VM] Adding additional disks to {name}...")

    for i, size in enumerate(disks, start=1):
        disk_path = os.path.join(vm_path, f"{name}_data{i}.vhdx")

        ps = f"""
if (-not (Test-Path "{disk_path}")) {{
    New-VHD -Path "{disk_path}" -SizeBytes {size}GB -Dynamic
    Add-VMHardDiskDrive -VMName "{name}" -Path "{disk_path}"
}}
"""
        run_ps(ps)


# ------------------------------------------------
# Attach ISO (based on role)
# ------------------------------------------------

def attach_iso(vm):
    name = vm["name"]
    role = vm.get("role")

    # Adjust paths if needed
    server_iso = r"C:\CVNP-Python\Python Projects\Lab Deployment\install_media\SERVER_EVAL_x64FRE_en-us.iso"
    win11_iso = r"C:\CVNP-Python\Python Projects\Lab Deployment\install_media\Windows_11_Eval.iso"

    iso_path = server_iso if role in ["router", "domain_controller"] else win11_iso

    print(f"[VM] Attaching ISO to {name}")

    ps = f"""
Set-VMDvdDrive `
    -VMName "{name}" `
    -Path "{iso_path}"
"""
    run_ps(ps)


# ------------------------------------------------
# Start VM
# ------------------------------------------------

def start_vm(name):
    print(f"[VM] Starting {name}")

    ps = f"""
if ((Get-VM -Name "{name}").State -ne "Running") {{
    Start-VM -Name "{name}"
}}
"""
    run_ps(ps)


# ------------------------------------------------
# Wait for VM heartbeat (integration service)
# ------------------------------------------------

def wait_for_vm(name, timeout=600):
    print(f"[VM] Waiting for {name} to boot...")

    import time
    start = time.time()

    while time.time() - start < timeout:
        try:
            ps = f"""
(Get-VM -Name "{name}").State
"""
            state = run_ps(ps, return_output=True)

            if state and "Running" in state:
                print(f"[VM] {name} is running.")
                return True

        except Exception:
            pass

        print(f"[VM] Waiting for {name}...")
        time.sleep(10)

    raise TimeoutError(f"{name} failed to start.")


# ------------------------------------------------
# Main Builder
# ------------------------------------------------

def build_all_vms():
    print("\n========== VM CREATION ==========\n")

    config = load_config()
    vms = config.get("virtual_machines", [])

    for vm in vms:
        create_vm(vm)
        attach_iso(vm)
        start_vm(vm)
        wait_for_vm(vm["name"])

    print("\n[VM] All VMs created and running.\n")