"""
main.py — ACME Hyper-V Lab Automation
Usage: python main.py [build|destroy|rebuild|status|reset]
"""
import argparse
import sys
import os

# ── Resolve project root so all relative paths work regardless of CWD ────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

from utils.powershell_runner import run_ps, run_ps_script, require_admin
from utils.checkpoint        import reset_state
from core.environment_builder import build_lab, reset_build

LAB_DESTROY_SCRIPT = os.path.join(PROJECT_ROOT, "destroy_lab.ps1")


def cmd_build():
    build_lab()


def cmd_destroy():
    print("\n🗑  Destroying lab...\n")
    if not os.path.exists(LAB_DESTROY_SCRIPT):
        print(f"[WARN] destroy_lab.ps1 not found at {LAB_DESTROY_SCRIPT} — skipping PS teardown")
    else:
        run_ps_script(LAB_DESTROY_SCRIPT)
    reset_state()
    reset_build()
    print("\nLab destroyed.\n")


def cmd_rebuild():
    print("\n🔄 Rebuilding lab...\n")
    cmd_destroy()
    cmd_build()


def cmd_status():
    print("\n📊 ACME Lab VM Status\n")
    run_ps(r"""
$vms = Get-VM | Where-Object { $_.Name -like "Acme*" }
if (-not $vms) {
    Write-Output "No ACME VMs found."
} else {
    $vms | Select-Object Name, State, CPUUsage,
        @{N='MemoryMB'; E={[math]::Round($_.MemoryAssigned/1MB)}},
        @{N='Uptime';   E={$_.Uptime}} |
        Format-Table -AutoSize
}
""")


def cmd_reset():
    print("\n🔁 Resetting state...\n")
    reset_state()
    reset_build()
    print("State reset. Run 'python main.py build' to redeploy.\n")


def main():
    require_admin()

    # Change working directory to project root so relative imports and paths work
    os.chdir(PROJECT_ROOT)

    parser = argparse.ArgumentParser(
        description="ACME Hyper-V Lab Automation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  build    Deploy the full lab from scratch
  destroy  Tear down all VMs, switches, and disks
  rebuild  destroy + build (full reset)
  status   Show current VM states
  reset    Clear deployment checkpoint state only
        """
    )
    parser.add_argument(
        "command",
        choices=["build", "destroy", "rebuild", "status", "reset"]
    )

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    dispatch = {
        "build":   cmd_build,
        "destroy": cmd_destroy,
        "rebuild": cmd_rebuild,
        "status":  cmd_status,
        "reset":   cmd_reset,
    }
    dispatch[args.command]()


if __name__ == "__main__":
    main()