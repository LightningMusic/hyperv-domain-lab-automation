import argparse

from utils.powershell_runner import run_ps_script, require_admin
from utils.checkpoint import reset_state

from core.environment_builder import build_lab


LAB_DESTROY_SCRIPT = "destroy_lab.ps1"


# ------------------------------------------------
# Destroy
# ------------------------------------------------

def destroy_lab():
    print("\nDestroying lab environment...\n")
    run_ps_script(LAB_DESTROY_SCRIPT)
    reset_state()


# ------------------------------------------------
# Commands
# ------------------------------------------------

def rebuild_lab():
    print("\nRebuilding lab...\n")
    destroy_lab()
    build_lab()


def show_status():
    from utils.powershell_runner import run_ps

    print("\n[STATUS] ACME Lab VMs\n")

    ps = """
    Get-VM | Where-Object {$_.Name -like "ACME-*"} |
    Select Name, State, CPUUsage, MemoryAssigned |
    Format-Table -AutoSize
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