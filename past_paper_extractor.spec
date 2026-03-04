# past_paper_extractor.spec
# ===========================
# PyInstaller build spec.
# Run: pyinstaller past_paper_extractor.spec
#
# Output: dist/PastPaperExtractor.exe (Windows)
#         dist/PastPaperExtractor     (Linux/Mac)

import sys
from pathlib import Path

APP_NAME = "PastPaperExtractor"
MAIN_SCRIPT = "main.py"

block_cipher = None

a = Analysis(
    [MAIN_SCRIPT],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=[
        # Include customtkinter themes and assets
        ("venv/Lib/site-packages/customtkinter", "customtkinter"),
    ],
    hiddenimports=[
        "customtkinter",
        "pdfplumber",
        "fitz",
        "reportlab",
        "PIL",
        "diskcache",
        "sqlite3",
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,             # compress with UPX for smaller file
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # no console window (set True for debugging)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",   # uncomment when you have an icon
)
