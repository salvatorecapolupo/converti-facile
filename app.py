"""ConvertiFacile — punto di ingresso."""
import os
import sys
import traceback

VERSION = "1.1"


def _fix_streams():
    # exe "windowed": stdout/stderr sono None e alcune librerie ci scrivono
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))


def _dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _log_crash():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "ConvertiFacile")
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "errore.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
        return path
    except OSError:
        return None


def main():
    _fix_streams()
    _dpi_aware()
    try:
        import ui
        ui.run()
    except Exception:
        log = _log_crash()
        try:
            import tkinter
            from tkinter import messagebox
            r = tkinter.Tk(); r.withdraw()
            messagebox.showerror("ConvertiFacile", "Errore imprevisto." + (f"\nDettagli in:\n{log}" if log else ""))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
