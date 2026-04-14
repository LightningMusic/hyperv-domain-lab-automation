import json
import os
import time

STATE_FILE = "deployment_state.json"


class Step:
    def __init__(self, name, action, validate, retries=3):
        self.name = name
        self.action = action
        self.validate = validate
        self.retries = retries


class Orchestrator:

    def __init__(self):
        self.steps = []
        self.state = self.load_state()

    # -------------------------
    # State Handling
    # -------------------------
    def load_state(self):
        if not os.path.exists(STATE_FILE):
            return {"completed": []}
        with open(STATE_FILE, "r") as f:
            return json.load(f)

    def save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=4)

    def is_completed(self, step_name):
        return step_name in self.state["completed"]

    def mark_complete(self, step_name):
        self.state["completed"].append(step_name)
        self.save_state()

    # -------------------------
    # Register Steps
    # -------------------------
    def add_step(self, step: Step):
        self.steps.append(step)

    # -------------------------
    # Execution Engine
    # -------------------------
    def run(self, tracker=None):

        for step in self.steps:

            if self.is_completed(step.name):
                print(f"[SKIP] {step.name}")
                continue

            if tracker:
                tracker.start(step.name)

            for attempt in range(step.retries):

                try:
                    step.action()

                    if step.validate():
                        if tracker:
                            tracker.success(step.name)

                        self.mark_complete(step.name)
                        break
                    else:
                        raise Exception("Validation failed")

                except Exception as e:

                    if attempt == step.retries - 1:
                        if tracker:
                            tracker.fail(step.name)
                        raise Exception(f"Step '{step.name}' failed after {step.retries} attempts: {str(e)}")