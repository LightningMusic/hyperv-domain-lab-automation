"""
main.py — ACME Hyper-V Lab Automation
Usage: python main.py [build|destroy|rebuild|status|reset]
"""
import argparse
import sys
import os
from prompt_toolkit import prompt

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
    os.chdir(PROJECT_ROOT)

    dispatch = {
        "build":   cmd_build,
        "destroy": cmd_destroy,
        "rebuild": cmd_rebuild,
        "status":  cmd_status,
        "reset":   cmd_reset,
    }

    parser = argparse.ArgumentParser(
        description="ACME Hyper-V Lab Automation Tool"
    )
    parser.add_argument(
        "command",
        nargs="?",  # <-- makes it optional
        choices=dispatch.keys()
    )

    args = parser.parse_args()

    # ── If command passed → run once (original behavior) ──
    if args.command:
        dispatch[args.command]()
        return

    # ── Interactive mode ──
    print("\n🧠 ACME Lab Interactive Mode")
    print("Type a command: build, destroy, rebuild, status, reset")
    print("Type 'help' or 'exit'\n")

    while True:
        try:
            cmd = prompt("ACME Lab > ")

            if not cmd:
                continue

            if cmd in ("exit", "quit"):
                print("Exiting.")
                break

            if cmd == "help":
                print("Commands:", ", ".join(dispatch.keys()))
                continue

            if cmd in dispatch:
                dispatch[cmd]()
            else:
                print(f"Unknown command: {cmd}")

        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()