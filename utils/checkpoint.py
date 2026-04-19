"""
utils/checkpoint.py
Step-level persistence so a failed deployment can resume where it left off.
Uses a path relative to this file's location (project-agnostic).
"""
import json
import os
from pathlib import Path

_PROJECT_ROOT    = Path(__file__).resolve().parent.parent
_CHECKPOINT_FILE = _PROJECT_ROOT / "logs" / "deployment_state.json"


def load_state() -> dict:
    if not _CHECKPOINT_FILE.exists():
        return {}
    try:
        with open(_CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict):
    _CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_CHECKPOINT_FILE, "w") as f:
        json.dump(state, f, indent=4)


def is_completed(step: str) -> bool:
    return bool(load_state().get(step, False))


def mark_completed(step: str):
    state = load_state()
    state[step] = True
    save_state(state)


def reset_state():
    if _CHECKPOINT_FILE.exists():
        _CHECKPOINT_FILE.unlink()
    print("[CHECKPOINT] State reset.")


def run_step(step_name: str, func):
    """Execute func only if step_name has not been marked completed."""
    print(f"\n[STEP] {step_name}")
    if is_completed(step_name):
        print(f"[SKIP] {step_name} already completed.")
        return
    func()
    mark_completed(step_name)
    print(f"[DONE] {step_name}")