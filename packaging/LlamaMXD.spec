# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
# PyInstaller spec for the Windows build. Run through packaging/build.py, which also puts the
# files the app looks up beside its exe (the manual, licenses and bundled tools) into the result.
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.dirname(SPECPATH)

# Everything under assets/ keeps its relative place: the code finds it through __file__.
assets = []
for folder, _, files in os.walk(os.path.join(ROOT, "assets")):
    for name in files:
        if name.startswith("."):
            continue
        rel = os.path.relpath(folder, ROOT)
        assets.append((os.path.join(folder, name), rel))

rl_datas, rl_binaries, rl_hidden = collect_all("rlottie_python")

# The log header reads each package's version from its installed metadata.
metadata = []
for dist in ("PySide6", "opencv-python", "Pillow", "ffmpeg-python"):
    metadata += copy_metadata(dist)

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=rl_binaries,
    datas=assets + rl_datas + metadata,
    hiddenimports=rl_hidden,
    excludes=["tkinter", "yt_dlp", "matplotlib", "scipy", "pytest", "IPython", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LlamaMXD",
    console=False,
    icon=os.path.join(ROOT, "assets", "llama.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LlamaMXD")
