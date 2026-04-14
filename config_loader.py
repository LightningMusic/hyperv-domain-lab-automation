import json
import os


CONFIG_PATH = r"C:\CVNP-Python\Python Projects\Lab Deployment\ACME_Automation_Steps.json"


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------
# ENVIRONMENT
# ------------------------------------------------

def get_environment():
    return load_config().get("environment", {})


def get_domain_config():
    env = get_environment()
    return {
        "name": env.get("domain_name", "ad.acme.edu"),
        "netbios": env.get("netbios_name", "ACME")
    }


def get_network_config():
    return get_environment().get("network", {})


# ------------------------------------------------
# ACTIVE DIRECTORY
# ------------------------------------------------

def get_ous():
    return load_config().get("active_directory", {}).get("organizational_units", [])


def get_users():
    return load_config().get("active_directory", {}).get("users", [])


# ------------------------------------------------
# INFRASTRUCTURE
# ------------------------------------------------

def get_shares():
    return load_config().get("shared_folders", [])


def get_home_directories():
    return load_config().get("home_directories", [])


# ------------------------------------------------
# DHCP
# ------------------------------------------------

def get_dhcp_config():
    return load_config().get("dhcp", {})


# ------------------------------------------------
# GPO
# ------------------------------------------------

def get_gpo_config():
    return load_config().get("gpo", {})


# ------------------------------------------------
# DOMAIN JOIN
# ------------------------------------------------

def get_domain_join():
    return load_config().get("domain_join", {})