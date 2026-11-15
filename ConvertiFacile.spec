# -*- mode: python ; coding: utf-8 -*-
# Generato a mano per ConvertiFacile 1.1:  pyinstaller --noconfirm --clean ConvertiFacile.spec
import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# librerie con file binari/dati che PyInstaller non sempre trova da solo
for pkg in ("tkinterdnd2", "pillow_heif", "pillow_jxl", "pymupdf", "pdf2docx", "docx", "pptx", "markdown", "xlrd"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass  # pacchetto opzionale non installato: l'app nasconde quel formato

icon = "ConvertiFacile.ico" if os.path.exists("ConvertiFacile.ico") else None

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["engine", "ui", "images", "docs", "sheets", "slides", "formats", "common", "icon"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "notebook", "tkinter.test"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ConvertiFacile",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX scatena falsi positivi degli antivirus su Windows
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
