import subprocess
import time
from utils.logger import get_logger

log = get_logger("ssh_runner")


class SSHRunner:
    """
    Executes commands on remote Linux hosts via SSH using the OpenSSH client.

    Designed for the ACME Ubuntu web server VM (AcmeWeb01).
    Requires the OpenSSH client to be installed on the Windows host,
    which is available by default on Windows 10 1809+ and Server 2019+.
    """

    def __init__(self, host, username="acmeadmin", password=None,
                 key_path=None, port=22, timeout=60):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.timeout = timeout

    # ------------------------------------------------
    # Build SSH command list
    # ------------------------------------------------

    def _build_command(self, remote_cmd):
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes" if self.key_path else "BatchMode=no",
            "-p", str(self.port),
        ]

        if self.key_path:
            cmd += ["-i", self.key_path]

        cmd.append(f"{self.username}@{self.host}")
        cmd.append(remote_cmd)

        return cmd

    # ------------------------------------------------
    # Execute a single command
    # ------------------------------------------------

    def run(self, command, raise_on_error=True):
        """
        Runs a shell command on the remote host.
        Returns stdout as a string.
        """

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
            raise RuntimeError(f"SSH command timed out on {self.host}: {command}")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout:
            log.debug(f"[SSH OUT] {stdout}")

        if stderr:
            log.debug(f"[SSH ERR] {stderr}")

        if raise_on_error and result.returncode != 0:
            raise RuntimeError(
                f"SSH command failed on {self.host} (exit {result.returncode}):\n"
                f"  Command: {command}\n"
                f"  Error:   {stderr}"
            )

        return stdout

    # ------------------------------------------------
    # Upload a file via SCP
    # ------------------------------------------------

    def upload(self, local_path, remote_path):
        """Copies a local file to the remote host using SCP."""

        log.info(f"[SCP] Uploading {local_path} → {self.host}:{remote_path}")

        cmd = [
            "scp",
            "-o", "StrictHostKeyChecking=no",
            "-P", str(self.port),
        ]

        if self.key_path:
            cmd += ["-i", self.key_path]

        cmd += [local_path, f"{self.username}@{self.host}:{remote_path}"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            raise RuntimeError(f"SCP upload failed: {result.stderr.strip()}")

        log.info(f"[SCP] Upload complete.")

    # ------------------------------------------------
    # Upload a string as a file (write inline)
    # ------------------------------------------------

    def write_file(self, remote_path, content):
        """Writes string content directly to a remote file using heredoc."""

        # Escape single quotes in content
        escaped = content.replace("'", "'\"'\"'")
        cmd = f"cat > {remote_path} << 'ACME_EOF'\n{content}\nACME_EOF"
        self.run(cmd)

    # ------------------------------------------------
    # Connectivity check with retry
    # ------------------------------------------------

    def wait_until_ready(self, timeout=300, poll=15):
        """Blocks until SSH is reachable or timeout expires."""

        log.info(f"[SSH] Waiting for {self.host} to become reachable...")
        start = time.time()

        while time.time() - start < timeout:
            try:
                result = self.run("echo ready", raise_on_error=False)
                if "ready" in result:
                    log.info(f"[SSH] {self.host} is online.")
                    return True
            except Exception:
                pass

            log.info(f"[SSH] {self.host} not ready yet, retrying...")
            time.sleep(poll)

        raise TimeoutError(f"Host {self.host} did not become reachable within {timeout}s.")

    # ------------------------------------------------
    # Run a list of commands in sequence
    # ------------------------------------------------

    def run_script(self, commands):
        """
        Runs a list of shell commands in order.
        Stops and raises on first failure.
        """

        for cmd in commands:
            self.run(cmd)


# ------------------------------------------------
# Default runner for the ACME web server
# ------------------------------------------------

def get_web_runner(host="192.168.4.45"):
    """Returns a pre-configured SSHRunner for AcmeWeb01."""
    return SSHRunner(
        host=host,
        username="acmeadmin",
        password="Password123!",
        port=22
    )


def run_ssh(host, command, username="acmeadmin", password=None,
            key_path=None, raise_on_error=True):
    """
    One-shot SSH execution convenience function.
    """
    runner = SSHRunner(
        host=host,
        username=username,
        password=password,
        key_path=key_path
    )
    return runner.run(command, raise_on_error=raise_on_error)