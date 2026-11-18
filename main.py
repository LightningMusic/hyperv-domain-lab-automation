"""
main.py - ACME Hyper-V Lab Automation

Usage: python main.py [command] [--dry-run] [--yes]

  preflight   read-only audit of the host; changes nothing
  build       stand the lab up (runs preflight first)
  status      show this lab's VMs (only objects this tool owns)
  destroy     remove the lab (only objects this tool owns)
  rebuild     destroy, then build
  doctor      clear broken VM records left behind by failed builds
  reset       forget the build checkpoint

With no command, an interactive prompt opens.
"""
import argparse
import os

from prompt_toolkit import prompt

# Resolve project root so all relative paths work regardless of CWD
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

from utils.powershell_runner import run_ps, require_admin
from utils.checkpoint        import reset_state
from core.environment_builder import build_lab, reset_build
from core.preflight           import run_preflight
from core.teardown            import teardown, remove_ghost_records
from core                     import ownership


def cmd_preflight(opts):
    print("\n🔎 Preflight (read-only)\n")
    run_preflight(raise_on_fail=False)


def cmd_build(opts):
    build_lab()


def cmd_destroy(opts):
    print("\n🗑  Destroy lab\n")
    teardown(dry_run=opts.dry_run, assume_yes=opts.yes)


def cmd_rebuild(opts):
    print("\n🔄 Rebuilding lab...\n")
    teardown(dry_run=opts.dry_run, assume_yes=opts.yes)
    if not opts.dry_run:
        build_lab()


def cmd_status(opts):
    print(f"\n📊 Lab VMs (tag '{ownership.tag()}')\n")
    run_ps(rf"""
$vms = Get-VM -ErrorAction SilentlyContinue | Where-Object {{ $_.Notes -match '^{ownership.tag()}(\s|$)' }}
if (-not $vms) {{
    Write-Output "No VMs owned by this lab."
}} else {{
    $vms | Select-Object Name, State, CPUUsage,
        @{{N='MemoryMB'; E={{[math]::Round($_.MemoryAssigned/1MB)}}}},
        @{{N='Uptime';   E={{$_.Uptime}}}} |
        Format-Table -AutoSize
}}
""")


def cmd_doctor(opts):
    print("\n🩺 Doctor\n")
    remove_ghost_records(assume_yes=opts.yes)


def cmd_reset(opts):
    print("\n🔁 Resetting build checkpoint...\n")
    reset_state()
    reset_build()
    print("Checkpoint reset. Run 'build' to redeploy.\n")


DISPATCH = {
    "preflight": cmd_preflight,
    "build":     cmd_build,
    "status":    cmd_status,
    "destroy":   cmd_destroy,
    "rebuild":   cmd_rebuild,
    "doctor":    cmd_doctor,
    "reset":     cmd_reset,
}


def main():
    require_admin()
    os.chdir(PROJECT_ROOT)

    parser = argparse.ArgumentParser(description="ACME Hyper-V Lab Automation Tool")
    parser.add_argument("command", nargs="?", choices=DISPATCH.keys())
    parser.add_argument("--dry-run", action="store_true", help="show what would happen; change nothing")
    parser.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    args = parser.parse_args()

    # One-shot mode
    if args.command:
        DISPATCH[args.command](args)
        return

    # Interactive mode
    print("\n🧠 ACME Lab Interactive Mode")
    print("Commands: " + ", ".join(DISPATCH))
    print("Add --dry-run to destroy/rebuild to preview.  Type 'help' or 'exit'.\n")

    while True:
        try:
            line = prompt("ACME Lab > ").strip()
            if not line:
                continue
            if line in ("exit", "quit"):
                print("Exiting.")
                break
            if line == "help":
                print(__doc__)
                continue

            tokens = line.split()
            cmd, flags = tokens[0], set(tokens[1:])
            if cmd not in DISPATCH:
                print(f"Unknown command: {cmd}")
                continue
            DISPATCH[cmd](argparse.Namespace(dry_run="--dry-run" in flags, yes="--yes" in flags))

        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
