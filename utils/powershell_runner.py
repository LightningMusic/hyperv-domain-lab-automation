import subprocess
import ctypes
import sys
from pathlib import Path
from datetime import datetime


class PowerShellRunner:
    """
    Central execution engine for all PowerShell commands.
    Used by every infrastructure module in the automation project.
    """

    def __init__(self, verbose=True, log_file=None, timeout=600):
        self.verbose = verbose
        self.timeout = timeout
        self.log_file = log_file

    # -----------------------------------------------------
    # Logging
    # -----------------------------------------------------

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"

        if self.verbose:
            print(line)

        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")

    # -----------------------------------------------------
    # Admin check
    # -----------------------------------------------------

    @staticmethod
    def ensure_admin():
        """
        Ensure script is running with administrator privileges.
        Hyper-V commands require admin rights.
        """

        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("ERROR: This script must be run as Administrator.")
            sys.exit(1)

    # -----------------------------------------------------
    # Execute PowerShell command
    # -----------------------------------------------------

    def run(self, command):
        """
        Execute a PowerShell command and return the output.
        """

        self.log(f"Executing PowerShell command:\n{command}")

        full_command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command",
            command
        ]

        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"PowerShell command timed out:\n{command}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout:
            self.log(f"OUTPUT:\n{stdout}")

        if stderr:
            self.log(f"ERROR:\n{stderr}")

        if result.returncode != 0:
            raise RuntimeError(
                f"\nPowerShell command failed.\n\n"
                f"Command:\n{command}\n\n"
                f"Error:\n{stderr}\n"
            )

        return stdout

    # -----------------------------------------------------
    # Execute PowerShell script
    # -----------------------------------------------------

    def run_script(self, script_path):
        """
        Run a PowerShell .ps1 script.
        """

        script_path = Path(script_path)

        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        command = f"& '{script_path}'"
        return self.run(command)


# ---------------------------------------------------------
# Singleton runner instance
# ---------------------------------------------------------

_runner = PowerShellRunner(
    verbose=True,
    log_file="logs/deployment.log"
)


# ---------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------

def run_ps(command, return_output=False):
    """
    Runs a PowerShell command.

    If return_output=True, returns stdout.
    Otherwise behaves normally.
    """

    result = _runner.run(command)

    if return_output:
        return result

    return None


def run_ps_script(path):
    return _runner.run_script(path)


def require_admin():
    PowerShellRunner.ensure_admin()