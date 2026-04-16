import time
from utils.ssh_runner import SSHRunner, get_web_runner
from utils.powershell_runner import run_ps
from utils.logger import get_logger

log = get_logger("linux_manager")

WEB_VM_NAME  = "AcmeWeb01"
WEB_VM_IP    = "192.168.4.45"
UBUNTU_USER  = "acmeadmin"
UBUNTU_PASS  = "Password123!"

LAB_ROOT     = r"C:\CVNP-Python\Python Projects\Lab Deployment\LabVMs"
UBUNTU_ISO   = r"C:\CVNP-Python\Python Projects\Lab Deployment\install_media\ubuntu-server.iso"
SWITCH_NAME  = "AcmeBusiness"


# ------------------------------------------------
# Hyper-V: Create Ubuntu VM
# ------------------------------------------------

def create_ubuntu_vm():
    """Creates the AcmeWeb01 Hyper-V VM and attaches the Ubuntu Server ISO."""

    import os
    vm_path = f"{LAB_ROOT}\\{WEB_VM_NAME}"

    log.info(f"[LINUX] Creating Ubuntu VM: {WEB_VM_NAME}")

    ps = f"""
$vmName = "{WEB_VM_NAME}"
$vmPath = "{vm_path}"
$vhdPath = "$vmPath\\{WEB_VM_NAME}.vhdx"

if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) {{
    Write-Output "VM already exists: $vmName"
    exit
}}

New-Item -Path $vmPath -ItemType Directory -Force

New-VHD -Path $vhdPath -SizeBytes 40GB -Dynamic

New-VM `
    -Name $vmName `
    -MemoryStartupBytes 2048MB `
    -Generation 1 `
    -VHDPath $vhdPath `
    -Path $vmPath `
    -SwitchName "{SWITCH_NAME}"

Set-VMProcessor -VMName $vmName -Count 2

# Ubuntu uses Gen 1 — attach ISO as IDE DVD
Set-VMDvdDrive -VMName $vmName -Path "{UBUNTU_ISO}"

# Disable Secure Boot (not needed for Ubuntu Gen 1)
# Set-VMFirmware not needed for Gen 1

Write-Output "Ubuntu VM created: $vmName"
"""
    run_ps(ps)


# ------------------------------------------------
# Hyper-V: Start Ubuntu VM
# ------------------------------------------------

def start_ubuntu_vm():
    log.info(f"[LINUX] Starting {WEB_VM_NAME}...")

    ps = f"""
if ((Get-VM -Name "{WEB_VM_NAME}").State -ne "Running") {{
    Start-VM -Name "{WEB_VM_NAME}"
}}
Write-Output "VM started."
"""
    run_ps(ps)


# ------------------------------------------------
# Wait for SSH to become available
# ------------------------------------------------

def wait_for_ssh(timeout=600):
    log.info(f"[LINUX] Waiting for SSH on {WEB_VM_IP}...")
    runner = SSHRunner(host=WEB_VM_IP, username=UBUNTU_USER, password=UBUNTU_PASS)
    runner.wait_until_ready(timeout=timeout)


# ------------------------------------------------
# Get SSH runner
# ------------------------------------------------

def _ssh():
    return get_web_runner(host=WEB_VM_IP)


# ------------------------------------------------
# Set static IP on Ubuntu
# ------------------------------------------------

def configure_static_ip():
    log.info(f"[LINUX] Configuring static IP {WEB_VM_IP}...")

    netplan_config = f"""network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
      addresses:
        - {WEB_VM_IP}/24
      gateway4: 192.168.4.1
      nameservers:
        addresses:
          - 192.168.4.3
          - 1.1.1.1
"""
    ssh = _ssh()
    ssh.write_file("/etc/netplan/01-lab-static.yaml", netplan_config)
    ssh.run("sudo netplan apply")
    log.info("[LINUX] Static IP applied.")


# ------------------------------------------------
# System update
# ------------------------------------------------

def update_system():
    log.info("[LINUX] Updating system packages...")

    ssh = _ssh()
    ssh.run("sudo apt-get update -y")
    ssh.run("sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y")
    log.info("[LINUX] System updated.")


# ------------------------------------------------
# Install Apache
# ------------------------------------------------

def install_apache():
    log.info("[LINUX] Installing Apache2...")

    ssh = _ssh()
    ssh.run("sudo apt-get install -y apache2")
    ssh.run("sudo systemctl enable apache2")
    ssh.run("sudo systemctl start apache2")
    log.info("[LINUX] Apache2 installed and started.")


# ------------------------------------------------
# Create virtual host: testweb.ad.acme.edu
# ------------------------------------------------

def create_vhost_testweb():
    log.info("[LINUX] Creating virtual host: testweb.ad.acme.edu")

    html = """<!DOCTYPE html>
<html>
<head><title>ACME TestWeb</title></head>
<body>
  <h1>ACME Lab - TestWeb</h1>
  <p>This is the internal test web server at testweb.ad.acme.edu</p>
</body>
</html>
"""

    vhost_conf = """<VirtualHost *:80>
    ServerName testweb.ad.acme.edu
    DocumentRoot /var/www/testweb

    <Directory /var/www/testweb>
        AllowOverride All
        Require all granted
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/testweb_error.log
    CustomLog ${APACHE_LOG_DIR}/testweb_access.log combined
</VirtualHost>
"""
    ssh = _ssh()
    ssh.run("sudo mkdir -p /var/www/testweb")
    ssh.write_file("/tmp/index_testweb.html", html)
    ssh.run("sudo mv /tmp/index_testweb.html /var/www/testweb/index.html")
    ssh.write_file("/tmp/testweb.conf", vhost_conf)
    ssh.run("sudo mv /tmp/testweb.conf /etc/apache2/sites-available/testweb.conf")
    ssh.run("sudo a2ensite testweb.conf")


# ------------------------------------------------
# Create virtual host: b2b.ad.acme.edu
# ------------------------------------------------

def create_vhost_b2b():
    log.info("[LINUX] Creating virtual host: b2b.ad.acme.edu")

    html = """<!DOCTYPE html>
<html>
<head><title>ACME B2B Portal</title></head>
<body>
  <h1>ACME Lab - B2B Portal</h1>
  <p>B2B partner portal at b2b.ad.acme.edu</p>
</body>
</html>
"""

    vhost_conf = """<VirtualHost *:80>
    ServerName b2b.ad.acme.edu
    DocumentRoot /var/www/b2b

    <Directory /var/www/b2b>
        AllowOverride All
        Require all granted
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/b2b_error.log
    CustomLog ${APACHE_LOG_DIR}/b2b_access.log combined
</VirtualHost>
"""
    ssh = _ssh()
    ssh.run("sudo mkdir -p /var/www/b2b")
    ssh.write_file("/tmp/index_b2b.html", html)
    ssh.run("sudo mv /tmp/index_b2b.html /var/www/b2b/index.html")
    ssh.write_file("/tmp/b2b.conf", vhost_conf)
    ssh.run("sudo mv /tmp/b2b.conf /etc/apache2/sites-available/b2b.conf")
    ssh.run("sudo a2ensite b2b.conf")


# ------------------------------------------------
# Reload Apache after all vhosts configured
# ------------------------------------------------

def reload_apache():
    log.info("[LINUX] Reloading Apache...")

    ssh = _ssh()
    ssh.run("sudo apache2ctl configtest")
    ssh.run("sudo systemctl reload apache2")
    log.info("[LINUX] Apache reloaded.")


# ------------------------------------------------
# Verify Apache is serving
# ------------------------------------------------

def verify_apache():
    log.info("[LINUX] Verifying Apache is serving...")

    ssh = _ssh()

    result = ssh.run(
        "curl -s -o /dev/null -w '%{http_code}' http://localhost/",
        raise_on_error=False
    )

    if result.strip() == "200":
        log.info("[LINUX] Apache is serving HTTP 200 ✅")
    else:
        log.warning(f"[LINUX] Apache returned: {result.strip()} ⚠")


# ------------------------------------------------
# Full provisioning pipeline
# ------------------------------------------------

def configure_linux_server():
    log.info("\n[LINUX] Starting Ubuntu web server provisioning...\n")

    # 1. Create and start VM (if not already running)
    create_ubuntu_vm()
    start_ubuntu_vm()

    # 2. Wait for SSH
    wait_for_ssh(timeout=600)

    # 3. Network
    configure_static_ip()

    # 4. System prep
    update_system()

    # 5. Apache
    install_apache()

    # 6. Virtual hosts
    create_vhost_testweb()
    create_vhost_b2b()
    reload_apache()

    # 7. Verify
    verify_apache()

    log.info("\n[LINUX] Ubuntu web server configuration COMPLETE.\n")
    log.info(f"  http://{WEB_VM_IP}")
    log.info("  http://testweb.ad.acme.edu")
    log.info("  http://b2b.ad.acme.edu")