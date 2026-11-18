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


class ConfigError(ValueError):
    """The configuration asks for something this tool refuses to do."""


def is_within_project(path) -> bool:
    """True if `path` resolves to somewhere inside the project folder."""
    try:
        Path(path).resolve().relative_to(PROJECT_ROOT)
        return True
    except ValueError:
        return False


def _abs(relative_or_absolute: str) -> str:
    """
    Return an absolute path, resolved against the project root if relative.

    CONTAINMENT: every path this tool reads or writes must stay inside the
    project folder.  A config value that resolves anywhere else (an absolute
    path to another drive, a '..' escape, a symlink out) is rejected.
    """
    p = Path(relative_or_absolute)
    p = (p if p.is_absolute() else PROJECT_ROOT / p).resolve()
    if not is_within_project(p):
        raise ConfigError(
            f"Path '{relative_or_absolute}' resolves to '{p}', which is outside "
            f"the project folder '{PROJECT_ROOT}'. Use a path relative to the project."
        )
    return str(p)


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


def get_lab_id():
    """Short id used to tag every Hyper-V object this lab creates."""
    return get_hyperv_config().get("lab_id", "acme")


def get_internal_switch():
    """Name of the lab's PRIVATE switch."""
    return get_hyperv_config().get("internal_switch", "AcmeBusiness")


def get_uplink_switch_name():
    return get_hyperv_config().get("uplink_switch", "Default Switch")


def get_uplink_switch_id():
    """Well-known GUID of Hyper-V's built-in Default Switch (name can be localized)."""
    return get_hyperv_config().get("uplink_switch_id", "C08CB7B8-9B3C-408E-8E30-5E16A3AEB444")


def get_preflight_config():
    cfg = load_config().get("preflight", {})
    return {
        "min_free_gb":     int(cfg.get("min_free_gb", 120)),
        "ram_headroom_gb": int(cfg.get("ram_headroom_gb", 8)),
    }


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