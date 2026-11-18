"""
utils/powershell_runner.py
Runs PowerShell commands and scripts from Python.
Always uses absolute paths so CWD doesn't matter.
"""
import subprocess
import ctypes
import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime

# Resolve project root from this file's location
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR  = _PROJECT_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "deployment.log"


_SECRET_PATTERNS = (
    re.compile(r'(ConvertTo-SecureString\s+")[^"]*(")', re.IGNORECASE),
    re.compile(r"(ConvertTo-SecureString\s+')[^']*(')", re.IGNORECASE),
    re.compile(r"(<Value>)[^<]*(</Value>)", re.IGNORECASE),
)


def redact(text):
    """Mask passwords before anything is printed, logged or put in an error."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1********\2", text)
    return text


class PowerShellRunner:
    def __init__(self, verbose=True, log_file=None, timeout=600):
        self.verbose  = verbose
        self.timeout  = timeout
        self.log_file = str(log_file) if log_file else None

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
        if sys.platform != "win32":
            return  # skip on non-Windows (dev/test)
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("ERROR: Must be run as Administrator.")
            sys.exit(1)

    def run(self, command, return_output=False, ignore_stderr=False, timeout=None, quiet=False):
        """quiet=True: do not write the command's stdout to the log or console."""
        timeout = timeout or self.timeout
        self.log(f"PS> {redact(command)[:300].strip()}")
        wrapped_command = (
            "$ErrorActionPreference = 'Stop'; "
            "$ProgressPreference = 'SilentlyContinue'; "
            + command
        )
        full_cmd = [
            "powershell", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", wrapped_command
        ]
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"PowerShell timed out after {timeout}s:\n{redact(command)[:200]}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout and not quiet:
            self.log(f"OUT: {redact(stdout)}")
        if stderr:
            self.log(f"ERR: {redact(stderr)}")

        if result.returncode != 0 and not ignore_stderr:
            raise RuntimeError(
                f"PowerShell failed (exit {result.returncode}).\n"
                f"CMD: {redact(command)[:300]}\nERR: {redact(stderr)}"
            )

        return stdout if return_output else None

    def run_script(self, script_path):
        p = Path(script_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Script not found: {p}")
        # Use & with full absolute path; no CWD dependency
        return self.run(f"& '{p}'", return_output=True)


_runner = PowerShellRunner(verbose=True, log_file=_LOG_FILE)


def run_ps(command, return_output=False, ignore_stderr=False, timeout=None):
    return _runner.run(command, return_output=return_output,
                       ignore_stderr=ignore_stderr, timeout=timeout)


def run_ps_json(command, timeout=None):
    """
    Run a PowerShell snippet whose last pipeline emits objects, and return them
    parsed from JSON (None for no output, a list if several objects).
    The snippet must NOT call ConvertTo-Json itself.
    """
    out = _runner.run(
        f"$__r = & {{ {command} }}; if ($null -ne $__r) {{ ConvertTo-Json -InputObject @($__r) -Compress -Depth 4 }}",
        return_output=True, timeout=timeout, quiet=True,
    )
    if not out:
        return None
    data = json.loads(out)
    return data[0] if isinstance(data, list) and len(data) == 1 else data


def run_ps_script(path):
    return _runner.run_script(path)


def require_admin():
    PowerShellRunner.ensure_admin()
