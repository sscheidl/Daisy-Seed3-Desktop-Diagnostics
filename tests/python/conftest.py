import os
import sys
from pathlib import Path

DIAG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DIAG / "windows"))
VECTORS = DIAG / "protocol" / "vectors.txt"

# GUI tests run headless; Windows fonts make screenshots readable.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
