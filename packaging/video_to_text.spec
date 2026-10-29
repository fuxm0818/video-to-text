# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for Video to Text (macOS app bundle / Windows folder)."""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
WEB = SRC / "video_to_text" / "web"
FFMPEG = ROOT / "packaging" / "ffmpeg"
ICON = ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns")

datas = [(str(WEB), "video_to_text/web")]
datas += collect_data_files("funasr")
datas += collect_data_files("modelscope")
binaries = [
    (str(path), ".")
    for path in sorted(FFMPEG.glob("*"))
    if path.is_file() and not path.name.startswith(".")
]

hiddenimports = []
for package in ("funasr", "modelscope", "transformers", "torchaudio"):
    hiddenimports += collect_submodules(package)

excludes = [
    "tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "tensorflow", "jax", "flax",
    "onnx", "onnxruntime", "cv2", "tensorboard", "mediapipe",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "packaging" / "hooks")],
    runtime_hooks=[str(ROOT / "packaging" / "runtime_hooks.py")],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoToText",
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
    icon=str(ICON) if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoToText",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="视频转文字.app",
        icon=str(ICON),
        bundle_identifier="com.fuxiangming.videototext",
        info_plist={
            "CFBundleDisplayName": "视频转文字",
            "CFBundleName": "视频转文字",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "MIT License",
        },
    )
