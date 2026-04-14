# Hyper-V Domain Lab Automation

## 🚀 Overview

This project is a **Python-based infrastructure automation tool** that builds a complete **Active Directory domain lab environment** from scratch using **Microsoft Hyper-V**.

Instead of manually configuring virtual machines and services, this system automates the entire deployment process—from virtual hardware creation to domain configuration, security policies, and workstation integration.

The result is a **fully functional enterprise-style network environment** that can be deployed or destroyed in minutes.

---

## 🎯 Key Features

* 🔧 Fully automated **Hyper-V infrastructure deployment**
* 🌐 Automatic **virtual networking and NAT routing**
* 🖥️ Builds **Windows Server 2022 domain controller**
* 💻 Deploys **Windows 11 workstation**
* 🧠 Configures **Active Directory, DNS, and DHCP**
* 👥 Creates **users, groups, and organizational units**
* 📂 Deploys **shared folders and drive mappings**
* 🔐 Applies **Group Policy security configurations**
* 🔁 One-command **lab teardown and cleanup**
* 🐧 Supports **Linux-based web server integration (Ubuntu)**

---

## 🏗️ What This Project Builds

When executed, the automation pipeline creates:

* A virtual switch
* A router VM with NAT
* A domain controller (Active Directory, DNS, DHCP)
* A workstation joined to the domain
* A structured Active Directory environment
* Shared network resources
* Enterprise-style security policies

---

## 🧱 Project Structure

```
Lab Deployment
│
├── ACME_Automation_Steps.json
├── config_loader.py
├── main.py
├── destroy_lab.ps1
├── Project-Overview.txt
│
├── core
│   ├── backup_manager.py
│   ├── dns_manager.py
│   ├── hyperv_manager.py
│   ├── linux_manager.py
│   ├── network_config.py
│   ├── orchestrator.py
│   ├── progress_tracker.py
│   ├── storage_manager.py
│   ├── validators.py
│   ├── vm_creator.py
│
├── domain
│   ├── ad_installer.py
│   ├── dhcp_config.py
│   ├── dhcp_reservations.py
│   ├── dns_records.py
│   ├── ou_manager.py
│   ├── user_manager.py
│
├── infrastructure
│   ├── domain_join.py
│   ├── failure_simulator.py
│   ├── gpo_manager.py
│   ├── shares.py
│
├── utils
│   ├── checkpoint.py
│   ├── logger.py
│   ├── powershell_runner.py
│   ├── ssh_runner.py
│
├── install_media
├── LabVMs
├── logs
└── unattended
```

---

## ⚙️ Requirements

* Windows 10/11 Pro or Enterprise
* **Hyper-V enabled**
* Python 3.10+
* Administrator privileges
* Virtualization enabled in BIOS

---

## 📦 Installation

1. Clone the repository:

```
git clone https://github.com/YOUR_USERNAME/hyperv-domain-lab-automation.git
cd hyperv-domain-lab-automation
```

2. Ensure Hyper-V is enabled:

```
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

3. Place installation media:

* Windows Server ISO → `install_media/`
* Windows 11 ISO → `install_media/`

⚠️ These files are **not included in the repository**

---

## ▶️ Usage

Run the deployment:

```
python main.py
```

This will:

1. Create virtual infrastructure
2. Configure networking and routing
3. Deploy domain controller
4. Configure Active Directory services
5. Create users and policies
6. Deploy workstation and join domain

---

## 🧹 Cleanup

Destroy the lab environment completely:

```
.\destroy_lab.ps1
```

This will:

* Stop and remove all VMs
* Delete virtual disks
* Remove virtual switches
* Clean up all lab files

---

## 🧠 Architecture Highlights

* **Modular Python design** for scalability
* **PowerShell integration** for Hyper-V control
* **Config-driven deployment** via JSON
* **Enterprise best practices** (AGDLP, OU structure, GPOs)
* **Single-folder lab design** for easy teardown
* **Cross-platform capability** (Windows + Linux server)

---

## 🔐 Security Concepts Demonstrated

* Active Directory delegation
* Group Policy enforcement
* Account lockout and password policies
* Network segmentation via virtual routing
* Controlled resource access via security groups

---

## 🧪 Use Cases

* Cybersecurity lab environments
* Active Directory practice
* Red team / blue team simulations
* IT training and certification prep
* Infrastructure automation learning

---

## ⚠️ Notes

* ISO files and VM disks are excluded via `.gitignore`
* Requires administrative privileges to execute
* Designed for lab/testing environments only

---

## 📈 Future Improvements

* Web-based dashboard for deployment control
* Automated attack simulation scenarios
* Logging and monitoring enhancements
* Multi-domain / forest support
* Cloud integration (Azure / hybrid environments)

---

## 👤 Author

Developed as part of a cybersecurity and infrastructure automation project.

---

## 📜 License

This project is intended for educational and lab use.
