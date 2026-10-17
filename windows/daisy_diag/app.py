"""Command line entry point."""
from __future__ import annotations

import argparse
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="DaisyDiagnostic",
        description="Hardware-Diagnose für das Daisy Seed3 Desktop Dev Kit")
    parser.add_argument("--sim", action="store_true",
                        help="im Simulationsmodus starten (ohne Hardware)")
    parser.add_argument("--port", help="festen COM-Port verwenden, z. B. COM5")
    parser.add_argument("--selftest", type=float, metavar="SEKUNDEN",
                        help="nach N Sekunden beenden; Exitcode 0, wenn Gerätedaten "
                             "empfangen wurden (für automatisierte Starttests)")
    parser.add_argument("--screenshot", metavar="DATEI",
                        help="vor dem Beenden (--selftest) ein Fensterbild speichern")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .gui import theme
    from .gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("DaisyDiagnostic")
    theme.apply(app)
    window = MainWindow(simulation=args.sim, port=args.port)
    window.show()
    result = {"code": 0}
    if args.selftest is not None:
        def finish() -> None:
            ok = window.session is not None and window.session.board is not None
            if args.screenshot:
                window.grab().save(args.screenshot)
            print(f"selftest: {'PASS' if ok else 'FAIL'} state={window.session.state.name}"
                  f" frames={window.session.frames_ok}", flush=True)
            result["code"] = 0 if ok else 1
            window.close()
            app.quit()
        QTimer.singleShot(int(args.selftest * 1000), finish)
    rc = app.exec()
    return result["code"] if args.selftest is not None else rc
