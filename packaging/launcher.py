"""Entry point used by PyInstaller builds (windowed, no console)."""
from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import traceback
from pathlib import Path


def _log_file() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "video-to-text" / "launch.log"


def _ensure_streams() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        path = _log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = handle
    if sys.stderr is None:
        sys.stderr = handle


def _notify(message: str) -> None:
    try:
        if sys.platform == "darwin":
            safe = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'display alert "视频转文字" message "{safe}" as critical'],
                timeout=30, check=False,
            )
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "视频转文字", 0x10)
    except Exception:
        pass


def main() -> int:
    multiprocessing.freeze_support()
    _ensure_streams()
    try:
        from video_to_text.app import main as app_main
        return app_main()
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        _notify(f"程序启动失败，详情见日志：\n{_log_file()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
