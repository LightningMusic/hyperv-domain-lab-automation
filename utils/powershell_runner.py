import subprocess
import ctypes
import sys
import os
from pathlib import Path
from datetime import datetime

# Absolute log path — never depends on CWD
_LOG_DIR  = r"C:\CVNP-Python\Python Projects\Lab Deployment\logs"
_LOG_FILE = os.path.join(_LOG_DIR, "deployment.log")


class PowerShellRunner:
    def __init__(self, verbose=True, log_file=None, timeout=600):
        self.verbose  = verbose
        self.timeout  = timeout
        self.log_file = log_file

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        if self.verbose:
            print(line)
        if self.log_file:
            try:
                os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    @staticmethod
    def ensure_admin():
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("ERROR: Must be run as Administrator.")
            sys.exit(1)

    def run(self, command, return_output=False):
        self.log(f"PS> {command[:200].strip()}")
        full_cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", command
        ]
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"PowerShell timed out:\n{command}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout: self.log(f"OUT: {stdout}")
        if stderr: self.log(f"ERR: {stderr}")

        if result.returncode != 0:
            raise RuntimeError(
                f"PowerShell failed (exit {result.returncode}).\n"
                f"CMD: {command}\nERR: {stderr}"
            )
        if return_output:
            return stdout
        return None

    def run_script(self, script_path):
        p = Path(script_path)
        if not p.exists():
            raise FileNotFoundError(f"Script not found: {p}")
        return self.run(f"& '{p}'", return_output=True)


_runner = PowerShellRunner(verbose=True, log_file=_LOG_FILE)


def run_ps(command, return_output=False):
    return _runner.run(command, return_output=return_output)

def run_ps_script(path):
    return _runner.run_script(path)

def require_admin():
    PowerShellRunner.ensure_admin()