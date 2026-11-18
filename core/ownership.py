"""
core/ownership.py - containment and ownership for everything this tool creates.

The host this runs on may also hold unrelated Hyper-V VMs, switches and files.
The rules enforced here (and used by create / preflight / teardown):

  1. NAME ALLOWLIST  - only VM and switch names defined in the config may ever
                       be created, modified or deleted.
  2. OWNERSHIP TAG   - every VM / switch we create gets a tag in its Hyper-V
                       Notes field.  An object with an allowed name but without
                       our tag is NOT ours and is never touched.
  3. MANIFEST        - everything created is also recorded in
                       state/manifest.json so a teardown can show exactly what
                       it is about to remove.
  4. PATH CONTAINMENT - files are only ever deleted from inside the project folder.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from config_loader import (
    PROJECT_ROOT, get_lab_id, get_vms, get_internal_switch, is_within_project,
)

STATE_DIR     = PROJECT_ROOT / "state"
MANIFEST_FILE = STATE_DIR / "manifest.json"
TAG_PREFIX    = "hvlab"


class OwnershipError(RuntimeError):
    """Refusing to touch something this tool does not own."""


# ── Tag ───────────────────────────────────────────────────────────────────────

def tag() -> str:
    """The ownership tag, e.g. 'hvlab:acme'."""
    return f"{TAG_PREFIX}:{get_lab_id()}"


def note(kind: str) -> str:
    """Text stored in the Hyper-V Notes field of an object we create."""
    return f"{tag()} kind={kind} tool=hyperv-domain-lab-automation"


def is_ours(notes: str | None) -> bool:
    """True only if the Notes text starts with our exact tag token."""
    if not notes:
        return False
    return re.match(rf"^{re.escape(tag())}(\s|$)", notes.strip()) is not None


def ps_owned(var: str = "$_") -> str:
    """
    PowerShell expression that is $true only for objects carrying our tag.
    Use it so the ownership test runs on the HOST and only a yes/no comes
    back: the Notes of objects that belong to something else are private and
    are never read into this program or its logs.
    """
    return rf"[bool]({var}.Notes -match '^{re.escape(tag())}(\s|$)')"


# ── Allowlists ────────────────────────────────────────────────────────────────

def lab_vm_names() -> list[str]:
    return [v["name"] for v in get_vms()]


def lab_switch_names() -> list[str]:
    return [get_internal_switch()]


def assert_vm_allowed(name: str) -> None:
    if name not in lab_vm_names():
        raise OwnershipError(f"VM '{name}' is not defined in this lab's config; refusing to touch it.")


def assert_switch_allowed(name: str) -> None:
    if name not in lab_switch_names():
        raise OwnershipError(f"Switch '{name}' is not this lab's switch; refusing to touch it.")


def assert_inside_project(path) -> Path:
    """Return the resolved path, or raise if it is outside the project folder."""
    p = Path(path).resolve()
    if not is_within_project(p):
        raise OwnershipError(f"'{p}' is outside the project folder; refusing to touch it.")
    return p


# ── Manifest ──────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("resources"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"lab_id": get_lab_id(), "resources": {}}


def _save(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, MANIFEST_FILE)


def record(kind: str, name: str, **info) -> None:
    """Record a resource we created (idempotent)."""
    data = _load()
    key = f"{kind}:{name}"
    entry = data["resources"].get(key, {})
    entry.update(info)
    entry.setdefault("created", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data["resources"][key] = entry
    _save(data)


def forget(kind: str, name: str) -> None:
    data = _load()
    if data["resources"].pop(f"{kind}:{name}", None) is not None:
        _save(data)


def entries() -> dict:
    return dict(_load()["resources"])


def clear() -> None:
    try:
        MANIFEST_FILE.unlink()
    except FileNotFoundError:
        pass
