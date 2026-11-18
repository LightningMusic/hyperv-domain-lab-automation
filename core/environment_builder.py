"""
core/environment_builder.py
Wires every deployment step together.  Called by main.py build command.
"""
import sys
import time

from config_loader import (
    load_config, get_router_name, get_dc_name,
    get_workstation_name, get_domain_config
)
from core.hyperv_manager import (
    create_lab_directory,
    generate_unattend_files,
    create_lab_switch,
    create_router_vm, create_domain_controller_vm, create_workstation_vm,
    start_all_vms,
    wait_for_all_installs,
    verify_environment_post,
)
from core.preflight           import run_preflight
from core.network_config      import configure_networking, configure_router, verify_router, renew_dhcp
from core.validators          import vm_exists, domain_exists, dhcp_configured, is_domain_joined, gpo_applied
from domain.ad_installer      import install_active_directory  as ad_install
from domain.dhcp_config       import configure_dhcp            as dhcp_install
from domain.ou_manager        import create_organizational_units
from domain.user_manager      import create_users_and_groups
from domain.dns_records       import configure_dns_records
from domain.dhcp_reservations import configure_dhcp_reservations
from infrastructure.gpo_manager  import configure_gpo
from infrastructure.domain_join  import join_workstations_to_domain
from infrastructure.shares       import setup_shares
from core.dns_manager            import configure_dns
from utils.logger                import get_logger

log = get_logger("environment_builder")

ROUTER_VM      = get_router_name()
DC_VM          = get_dc_name()
WORKSTATION_VM = get_workstation_name()
DOMAIN_NAME    = get_domain_config()["name"]

# Track timing for each phase
_phase_times: dict = {}


def _phase(title: str):
    """Print a prominent phase banner and record start time."""
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}\n")
    _phase_times[title] = time.time()


def _phase_done(title: str):
    elapsed = time.time() - _phase_times.get(title, time.time())
    log.info(f"[PHASE DONE] {title} ({elapsed:.0f}s)")


def _run_phase(title: str, func):
    _phase(title)
    try:
        func()
        _phase_done(title)
    except Exception as e:
        log.error(f"[PHASE FAILED] {title}: {e}")
        raise


# ── Individual phases ─────────────────────────────────────────────────────────

def deploy_vms():
    create_lab_directory()
    generate_unattend_files()
    create_lab_switch()                  # PRIVATE switch: no host IP / NAT / bridge
    create_router_vm()                   # 2nd NIC "Uplink" on the Default Switch
    create_domain_controller_vm()
    create_workstation_vm()
    start_all_vms()                      # also presses the "boot from DVD" key
    # Wait for all three VMs to finish OS install in parallel
    wait_for_all_installs(timeout_minutes=120)


def configure_infrastructure():
    configure_networking([WORKSTATION_VM])
    ad_install()
    configure_dns()
    dhcp_install()
    configure_dhcp_reservations()
    configure_dns_records()
    create_organizational_units()
    create_users_and_groups()
    setup_shares(load_config())


def join_domain_phase():
    renew_dhcp(WORKSTATION_VM)           # the DC's DHCP server is up now: get a lease + DNS
    join_workstations_to_domain()
    if not is_domain_joined(WORKSTATION_VM):
        raise RuntimeError("Workstation failed to join domain")


def apply_policies():
    configure_gpo()


def validate_environment_post():
    verify_environment_post()
    if not gpo_applied(WORKSTATION_VM):
        log.warning("[WARN] GPO not yet applied — may need gpupdate /force on workstation")
    log.info("[SUCCESS] Environment fully validated ✅")


# ── Main entry point ──────────────────────────────────────────────────────────

def _router_only_phases(ram_headroom_gb):
    """Smoke test of the network core: switch + router VM + NAT, nothing else."""
    def validate():
        run_preflight(vm_names=[ROUTER_VM], ram_headroom_gb=ram_headroom_gb)

    def deploy():
        create_lab_directory()
        generate_unattend_files()
        create_lab_switch()
        create_router_vm()
        start_all_vms(names=[ROUTER_VM])
        wait_for_all_installs(timeout_minutes=60, names=[ROUTER_VM])

    return [
        ("Validation (router only)", validate),
        ("Router Deployment",        deploy),
        ("Router Networking",        configure_router),
        ("Router Verification",      verify_router),
    ]


def build_lab(only: str | None = None, ram_headroom_gb: int | None = None):
    start = time.time()
    if only == "router":
        print("\n🚀 ROUTER-ONLY DEPLOYMENT STARTED (switch + router VM + NAT)\n")
        phases = _router_only_phases(ram_headroom_gb)
    elif only:
        raise ValueError(f"unknown build scope: {only!r}")
    else:
        print("\n🚀 FULL LAB DEPLOYMENT STARTED\n")
        phases = [
            ("Validation",        lambda: run_preflight(ram_headroom_gb=ram_headroom_gb)),
            ("VM Deployment",     deploy_vms),
            ("Infrastructure",    configure_infrastructure),
            ("Domain Join",       join_domain_phase),
            ("Group Policy",      apply_policies),
            ("Post Validation",   validate_environment_post),
        ]

    for title, func in phases:
        _run_phase(title, func)

    total = time.time() - start
    mins, secs = divmod(int(total), 60)
    print(f"\n🎉 LAB DEPLOYMENT COMPLETE  (total: {mins}m {secs}s)\n")


def reset_build():
    from utils.checkpoint import reset_state
    reset_state()
    log.info("[RESET] Build state cleared.")