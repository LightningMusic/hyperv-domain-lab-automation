import json
import os

_CHECKPOINT_FILE = r"C:\CVNP-Python\Python Projects\Lab Deployment\logs\deployment_state.json"

def load_state():
    if not os.path.exists(_CHECKPOINT_FILE):
        return {}
    with open(_CHECKPOINT_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    os.makedirs(os.path.dirname(_CHECKPOINT_FILE), exist_ok=True)
    with open(_CHECKPOINT_FILE, "w") as f:
        json.dump(state, f, indent=4)

def is_completed(step):
    return load_state().get(step, False)

def mark_completed(step):
    state = load_state()
    state[step] = True
    save_state(state)

def reset_state():
    if os.path.exists(_CHECKPOINT_FILE):
        os.remove(_CHECKPOINT_FILE)
    print("[CHECKPOINT] State reset.")

def run_step(step_name, func):
    print(f"\n[STEP] {step_name}")
    if is_completed(step_name):
        print(f"[SKIP] {step_name} already completed.")
        return
    func()
    mark_completed(step_name)
    print(f"[DONE] {step_name}")