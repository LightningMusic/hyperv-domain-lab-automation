import os

class CleanupVerifier:

    def __init__(self, lab_path):
        self.lab_path = lab_path

    def check_lab_folder_empty(self):
        for root, dirs, files in os.walk(self.lab_path):
            if files or dirs:
                return False
        return True

    def find_leftover_vhds(self):
        leftovers = []

        for root, _, files in os.walk(self.lab_path):
            for f in files:
                if f.endswith(".vhdx") or f.endswith(".avhdx"):
                    leftovers.append(os.path.join(root, f))

        return leftovers

    def verify(self):
        leftovers = self.find_leftover_vhds()
        empty = self.check_lab_folder_empty()

        return {
            "folder_empty": empty,
            "leftover_disks": leftovers,
            "cleanup_success": empty and len(leftovers) == 0
        }