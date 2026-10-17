"""Entry point for PyInstaller and for `python DaisyDiagnostic.py`."""
import sys

from daisy_diag.app import main

if __name__ == "__main__":
    sys.exit(main())
