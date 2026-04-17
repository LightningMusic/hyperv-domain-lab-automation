"""
main.py — ACME Hyper-V Lab Automation
Usage: python main.py [build|destroy|rebuild|status|reset]
"""
import argparse, sys
from utils.powershell_runner import run_ps, run_ps_script, require_admin
from utils.checkpoint        import reset_state
from core.environment_builder import build_lab, reset_build

LAB_DESTROY_SCRIPT = "destroy_lab.ps1"

def cmd_build():   build_lab()

def cmd_destroy():
    print("\n🗑  Destroying lab...\n")
    run_ps_script(LAB_DESTROY_SCRIPT)
    reset_state(); reset_build()
    print("\nLab destroyed.\n")

def cmd_rebuild():
    print("\n🔄 Rebuilding lab...\n"); cmd_destroy(); cmd_build()

def cmd_status():
    print("\n📊 ACME Lab VM Status\n")
    # VMs are named "Acme*" not "ACME-*"
    run_ps(r"""
$vms = Get-VM | Where-Object { $_.Name -like "Acme*" }
if (-not $vms) { Write-Output "No ACME VMs found." }
else {
    $vms | Select-Object Name, State, CPUUsage,
        @{N='MemoryMB';E={[math]::Round($_.MemoryAssigned/1MB)}} |
        Format-Table -AutoSize
}
""")

def cmd_reset():
    print("\n🔁 Resetting state...\n")
    reset_state(); reset_build()
    print("State reset. Run 'python main.py build' to redeploy.\n")

def main():
    require_admin()
    parser = argparse.ArgumentParser(description="ACME Hyper-V Lab Automation Tool")
    parser.add_argument("command", choices=["build","destroy","rebuild","status","reset"])
    if len(sys.argv) < 2:
        parser.print_help(); sys.exit(1)
    args = parser.parse_args()
    {"build":cmd_build,"destroy":cmd_destroy,"rebuild":cmd_rebuild,
     "status":cmd_status,"reset":cmd_reset}[args.command]()

if __name__ == "__main__":
    main()