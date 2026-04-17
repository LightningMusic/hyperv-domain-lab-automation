import subprocess
import time
from utils.logger import get_logger

log = get_logger("ssh_runner")


class SSHRunner:
    """SSH/SCP execution engine for Linux VMs (AcmeWeb01)."""

    def __init__(self, host, username="acmeadmin", password=None,
                 key_path=None, port=22, timeout=60):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.timeout = timeout

    def _build_command(self, remote_cmd):
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=NUL",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes" if self.key_path else "BatchMode=no",
            "-p", str(self.port),
        ]
        if self.key_path:
            cmd += ["-i", self.key_path]
        cmd.append(f"{self.username}@{self.host}")
        cmd.append(remote_cmd)
        return cmd

    def run(self, command, raise_on_error=True):
        log.debug(f"[SSH] {self.host}: {command}")
        full_cmd = self._build_command(command)

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"SSH timed out on {self.host}: {command}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout:
            log.debug(f"[SSH OUT] {stdout}")
        if stderr:
            log.debug(f"[SSH ERR] {stderr}")

        if raise_on_error and result.returncode != 0:
            raise RuntimeError(
                f"SSH failed on {self.host} (exit {result.returncode}):\n"
                f"  cmd: {command}\n  err: {stderr}"
            )
        return stdout

    def upload(self, local_path, remote_path):
        log.info(f"[SCP] {local_path} → {self.host}:{remote_path}")
        cmd = ["scp", "-o", "StrictHostKeyChecking=no", "-P", str(self.port)]
        if self.key_path:
            cmd += ["-i", self.key_path]
        cmd += [local_path, f"{self.username}@{self.host}:{remote_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"SCP failed: {result.stderr.strip()}")

    def write_file(self, remote_path, content):
        """Write a string directly to a remote file via stdin pipe."""
        cmd = self._build_command(f"cat > {remote_path}")
        result = subprocess.run(
            cmd,
            input=content,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"write_file failed for {remote_path}: {result.stderr.strip()}")

    def wait_until_ready(self, timeout=300, poll=15):
        log.info(f"[SSH] Waiting for {self.host}...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                out = self.run("echo ready", raise_on_error=False)
                if "ready" in out:
                    log.info(f"[SSH] {self.host} is online.")
                    return True
            except Exception:
                pass
            log.info(f"[SSH] {self.host} not ready, retrying in {poll}s...")
            time.sleep(poll)
        raise TimeoutError(f"{self.host} not reachable after {timeout}s.")

    def run_script(self, commands):
        for cmd in commands:
            self.run(cmd)


def get_web_runner(host="192.168.4.45"):
    return SSHRunner(host=host, username="acmeadmin", password="Password123!", port=22)


def run_ssh(host, command, username="acmeadmin", key_path=None, raise_on_error=True):
    return SSHRunner(host=host, username=username, key_path=key_path).run(
        command, raise_on_error=raise_on_error
    )