# core/environment_builder.py

from config_loader import load_config

# Core systems (NEW unified functions)
from core.hyperv_manager import (
    verify_environment,
    create_vm,
    start_vm,
    wait_for_install,
    install_active_directory,
    configure_dhcp,
    join_domain,
)

# VM builder (renamed function)
from core.vm_builder import build_all

# Domain
from domain.ou_manager import create_organizational_units
from domain.user_manager import create_users_and_groups

# Validation
from core.validators import is_domain_joined, gpo_applied


# ------------------------------------------------
# Helpers
# ------------------------------------------------

def get_vm_name(role):
    config = load_config()
    for vm in config["virtual_machines"]:
        if vm["role"] == role:
            return vm["name"]
    raise Exception(f"VM role not found: {role}")


# ------------------------------------------------
# PHASE 1: Validation / Prep
# ------------------------------------------------

def validate_environment():
    print("\n[PHASE] Validation\n")
    verify_environment()


# ------------------------------------------------
# PHASE 2: VM Deployment
# ------------------------------------------------

def deploy_vms():
    print("\n[PHASE] VM Deployment\n")
    build_all()


# ------------------------------------------------
# PHASE 3: Infrastructure
# ------------------------------------------------

def configure_infrastructure():
    print("\n[PHASE] Infrastructure\n")

    install_active_directory()
    configure_dhcp()
    create_organizational_units()
    create_users_and_groups()


# ------------------------------------------------
# PHASE 4: Domain Join
# ------------------------------------------------

def join_domain_phase():
    print("\n[PHASE] Domain Join\n")

    join_domain()

    if not is_domain_joined(get_vm_name("workstation")):
        raise Exception("Workstation failed to join domain")


# ------------------------------------------------
# PHASE 5: Validation
# ------------------------------------------------

def validate_environment_post():
    print("\n[PHASE] Validation (Post)\n")

    if not gpo_applied(get_vm_name("workstation")):
        raise Exception("GPO not applied")

    print("[SUCCESS] Environment fully validated ✅")


# ------------------------------------------------
# FULL PIPELINE
# ------------------------------------------------

def build_lab():
    print("\n🚀 FULL LAB DEPLOYMENT STARTED\n")

    validate_environment()
    deploy_vms()
    configure_infrastructure()
    join_domain_phase()
    validate_environment_post()

    print("\n🎉 LAB DEPLOYMENT COMPLETE\n")