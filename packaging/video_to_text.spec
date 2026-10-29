# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for Video to Text (macOS app bundle / Windows folder)."""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
ASSETS = SRC / "video_to_text" / "assets"
FFMPEG = ROOT / "packaging" / "ffmpeg"
ICON = ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns")

datas = [(str(ASSETS), "video_to_text/assets")]
datas += collect_data_files("funasr")
datas += collect_data_files("modelscope")
binaries = [
    (str(path), ".")
    for path in sorted(FFMPEG.glob("*"))
    if path.is_file() and path.name in {"ffmpeg", "ffmpeg.exe"}
]

hiddenimports = []
for package in ("funasr", "modelscope", "transformers", "torchaudio"):
    hiddenimports += collect_submodules(package)

excludes = [
    "tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest",
    "PyQt5", "PyQt6", "PySide2", "tensorflow", "jax", "flax",
    "onnx", "onnxruntime", "cv2", "tensorboard", "mediapipe",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtSensors", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtHelp", "PySide6.QtDesigner",
    "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
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
