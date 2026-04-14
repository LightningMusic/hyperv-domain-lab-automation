class ProgressTracker:

    def __init__(self):
        self.status = {}

    def start(self, step):
        self.status[step] = "RUNNING"
        self.display()

    def success(self, step):
        self.status[step] = "SUCCESS"
        self.display()

    def fail(self, step):
        self.status[step] = "FAILED"
        self.display()

    def display(self):
        print("\n===== DEPLOYMENT PROGRESS =====")

        for step, state in self.status.items():

            icon = {
                "RUNNING": "⏳",
                "SUCCESS": "✔",
                "FAILED": "✖"
            }.get(state, "?")

            print(f"[{icon}] {step}")

        print("================================\n")