"""
core/environment_builder.py
Wires every deployment step together. Called by main.py build command.
"""
from config_loader import (
    load_config, get_router_name, get_dc_name,
    get_workstation_name, get_domain_config
)
from core.hyperv_manager import (
    verify_environment,
    create_lab_directory,
    generate_unattend_files,
    create_external_switch,
    create_router_vm, create_domain_controller_vm, create_workstation_vm,
    configure_router_network,
    start_all_vms,
    wait_for_all_installs,
    install_active_directory,
    configure_dhcp,
    join_domain,
    verify_environment_post,
)
from core.vm_builder        import build_all
from core.network_config    import configure_networking
from core.validators        import vm_exists, domain_exists, dhcp_configured, is_domain_joined, gpo_applied
from domain.ad_installer    import install_active_directory  as ad_install
from domain.dhcp_config     import configure_dhcp            as dhcp_install
from domain.ou_manager      import create_organizational_units
from domain.user_manager    import create_users_and_groups
from domain.dns_records     import configure_dns_records
from domain.dhcp_reservations import configure_dhcp_reservations
from infrastructure.gpo_manager  import configure_gpo
from infrastructure.domain_join  import join_workstations_to_domain
from infrastructure.shares       import setup_shares
from core.dns_manager            import configure_dns

ROUTER_VM      = get_router_name()
DC_VM          = get_dc_name()
WORKSTATION_VM = get_workstation_name()
DOMAIN_NAME    = get_domain_config()["name"]


def get_vm_name(role):
    for vm in load_config()["virtual_machines"]:
        if vm["role"] == role:
            return vm["name"]
    raise ValueError(f"No VM with role: {role}")


# ── Phase helpers (kept for backward compat) ──────────────────────────────────

def validate_environment():
    print("\n[PHASE] Validation\n")
    verify_environment()

def deploy_vms():
    print("\n[PHASE] VM Deployment\n")
    create_lab_directory()
    generate_unattend_files()
    create_external_switch()
    create_router_vm()
    configure_router_network()
    create_domain_controller_vm()
    create_workstation_vm()
    start_all_vms()
    wait_for_all_installs()

def configure_infrastructure():
    print("\n[PHASE] Infrastructure\n")
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
    print("\n[PHASE] Domain Join\n")
    join_workstations_to_domain()
    if not is_domain_joined(WORKSTATION_VM):
        raise RuntimeError("Workstation failed to join domain")

def apply_policies():
    print("\n[PHASE] Group Policy\n")
    configure_gpo()

def validate_environment_post():
    print("\n[PHASE] Post-deploy Validation\n")
    verify_environment_post()
    if not gpo_applied(WORKSTATION_VM):
        print("[WARN] GPO not yet applied — may need gpupdate /force on workstation")
    print("[SUCCESS] Environment fully validated ✅")


# ── Main entry point ──────────────────────────────────────────────────────────

def build_lab():
    print("\n🚀 FULL LAB DEPLOYMENT STARTED\n")
    validate_environment()
    deploy_vms()
    configure_infrastructure()
    join_domain_phase()
    apply_policies()
    validate_environment_post()
    print("\n🎉 LAB DEPLOYMENT COMPLETE\n")


def reset_build():
    from utils.checkpoint import reset_state
    reset_state()
    print("[RESET] Build state cleared.")