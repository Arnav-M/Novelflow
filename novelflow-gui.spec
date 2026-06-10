# -*- mode: python ; coding: utf-8 -*-
# Folder build (onedir) — much faster startup than single-file extract.
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ("src/novelflow/assets/icon.ico", "novelflow/assets"),
    ("src/novelflow/assets/icon.png", "novelflow/assets"),
]
binaries = []
hiddenimports = [
    "novelflow",
    "novelflow.gui",
    "novelflow.convert",
    "novelflow.refine",
    "novelflow.paths",
    "novelflow.pdf_extract",
    "novelflow.pdf_italics",
    "novelflow.text_cleanup",
    "novelflow.gui_theme",
]

for pkg in ("pymupdf",):
    try:
        collected = collect_all(pkg)
        datas += collected[0]
        binaries += collected[1]
        hiddenimports += collected[2]
    except Exception:
        pass

a = Analysis(
    ["src/novelflow/gui_entry.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
        "notebook",
        "tkinter.test",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Novelflow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="src/novelflow/assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Novelflow",
)
