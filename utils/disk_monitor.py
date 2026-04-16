import os
from pathlib import Path

class DiskMonitor:
    def __init__(self, lab_path):
        self.lab_path = Path(lab_path)

    def get_folder_size(self, path=None):
        if path is None:
            path = self.lab_path

        total_size = 0

        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)

        return total_size

    def get_size_mb(self):
        return round(self.get_folder_size() / (1024 * 1024), 2)

    def get_size_gb(self):
        return round(self.get_folder_size() / (1024 * 1024 * 1024), 2)

    def report(self):
        return {
            "bytes": self.get_folder_size(),
            "mb": self.get_size_mb(),
            "gb": self.get_size_gb()
        }