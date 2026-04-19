"""
config_loader.py — Single source of truth for all configuration.
Paths are resolved relative to the project root (this file's parent directory)
so the tool works regardless of where it is cloned or what CWD is set to.
"""

import json
import os
from pathlib import Path

# Project root = directory containing this file
PROJECT_ROOT = Path(__file__).resolve().parent

# Config is always next to this file
CONFIG_PATH = PROJECT_ROOT / "ACME_Automation_Steps.json"

_cache = None


def load_config():
    global _cache
    if _cache is None:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def reload_config():
    global _cache
    _cache = None
    return load_config()


def _abs(relative_or_absolute: str) -> str:
    """
    Return an absolute path.  If the config value is already absolute, use it.
    Otherwise resolve it relative to the project root.
    """
    p = Path(relative_or_absolute)
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / p)


# ------------------------------------------------------------------ PATHS ---

def get_paths():
    return load_config().get("paths", {})


def get_lab_root():
    return _abs(get_paths().get("lab_root", "LabVMs"))


def get_unattend_dir():
    return _abs(get_paths().get("unattend_dir", "temp_unattend"))


def get_log_dir():
    return _abs(get_paths().get("log_dir", "logs"))


# --------------------------------------------------------- INSTALL MEDIA ---

def get_install_media():
    return load_config().get("install_media", {})


def get_server_iso():
    v = get_install_media().get("server_iso", "")
    return _abs(v) if v else str(PROJECT_ROOT / "install_media" / "SERVER_EVAL_x64FRE_en-us.iso")


def get_win11_iso():
    v = get_install_media().get("windows_iso", "")
    return _abs(v) if v else str(PROJECT_ROOT / "install_media" / "Windows_11_Eval.iso")


def get_ubuntu_iso():
    v = get_install_media().get("Ubuntu_server_iso", "")
    return _abs(v) if v else str(PROJECT_ROOT / "install_media" / "Ubuntu-24.04.4-live-server-amd64.iso")


# ------------------------------------------------------------ ENVIRONMENT ---

def get_environment():
    return load_config().get("environment", {})


def get_domain_config():
    env = get_environment()
    return {
        "name":               env.get("domain_name",        "ad.acme.edu"),
        "netbios":            env.get("netbios_name",        "ACME"),
        "admin_password":     env.get("admin_password",      "Password123!"),
        "safe_mode_password": env.get("safe_mode_password",  "Password123!"),
    }


def get_network_config():
    return get_environment().get("network", {})


def get_admin_password():
    return get_environment().get("admin_password", "Password123!")


def get_safe_mode_password():
    return get_environment().get("safe_mode_password", "Password123!")


# --------------------------------------------------------------- HYPER-V ---

def get_hyperv_config():
    return load_config().get("hyperv", {})


def get_internal_switch():
    return get_hyperv_config().get("internal_switch", "AcmeBusiness")


def get_external_switch():
    return get_hyperv_config().get("external_switch", "ACME-External")


# -------------------------------------------------------- VIRTUAL MACHINES --

def get_vms():
    return load_config().get("virtual_machines", [])


def get_vm_by_role(role):
    for vm in get_vms():
        if vm.get("role") == role:
            return vm
    return {}


def get_vm_name(role):
    return get_vm_by_role(role).get("name", "")


def get_router_name():      return get_vm_name("router")
def get_dc_name():          return get_vm_name("domain_controller")
def get_workstation_name(): return get_vm_name("workstation")
def get_storage_vm_name():  return get_vm_name("storage")
def get_web_vm_name():      return get_vm_name("web")


# ------------------------------------------------------- ACTIVE DIRECTORY ---

def get_ous():
    return load_config().get("active_directory", {}).get("organizational_units", [])


def get_users():
    return load_config().get("active_directory", {}).get("users", [])


# ----------------------------------------------------------------- SHARES ---

def get_shares():
    return load_config().get("shared_folders", [])


def get_home_directories():
    return load_config().get("home_directories", [])


# ------------------------------------------------------------------ DHCP ----

def get_dhcp_config():
    return load_config().get("dhcp", {})


# ------------------------------------------------------------------- GPO ----

def get_gpo_config():
    return load_config().get("gpo", {})


# ----------------------------------------------------------- DOMAIN JOIN ----

def get_domain_join():
    return load_config().get("domain_join", {})