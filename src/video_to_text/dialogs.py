"""Native file/folder pickers without tkinter.

The web UI runs in a browser, which cannot reveal absolute paths. Instead the
local server asks the operating system for a native dialog and returns the
selected paths to the page.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()


class DialogError(RuntimeError):
    pass


def pick_files() -> list[Path]:
    with _LOCK:
        if sys.platform == "darwin":
            return _pick_files_macos()
        if sys.platform == "win32":
            return _pick_files_windows()
        return _pick_files_linux()


def pick_folder() -> Path | None:
    with _LOCK:
        if sys.platform == "darwin":
            return _pick_folder_macos()
        if sys.platform == "win32":
            return _pick_folder_windows()
        return _pick_folder_linux()


# ------------------------------------------------------------------- macOS

_FILE_SCRIPT = """
try
    set theFiles to choose file with prompt "选择视频或音频文件（可多选）" with multiple selections allowed
    set outText to ""
    repeat with f in theFiles
        set outText to outText & POSIX path of f & linefeed
    end repeat
    return outText
on error number -128
    return ""
end try
"""

_FOLDER_SCRIPT = """
try
    set theFolder to choose folder with prompt "选择视频所在文件夹"
    return POSIX path of theFolder
on error number -128
    return ""
end try
"""


def _run_osascript(script: str) -> str:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DialogError(f"无法打开系统选择框：{exc}") from exc
    if r.returncode != 0:
        detail = (r.stderr or "").strip()
        if "-128" in detail or "cancel" in detail.lower() or "取消" in detail:
            return ""
        raise DialogError(f"系统选择框出错：{detail[-300:]}")
    return r.stdout


def _existing(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        raw = raw.strip()
        if not raw:
            continue
        path = Path(raw.rstrip("/") or "/")
        if path.exists():
            out.append(path)
    return out


def _pick_files_macos() -> list[Path]:
    return _existing(_run_osascript(_FILE_SCRIPT).splitlines())


def _pick_folder_macos() -> Path | None:
    folders = _existing([_run_osascript(_FOLDER_SCRIPT).strip()])
    return folders[0] if folders else None


# ----------------------------------------------------------------- Windows

_WIN_FILE_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '选择视频或音频文件（可多选）'
$dialog.Multiselect = $true
$dialog.Filter = '视频和音频|*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.ts;*.flv;*.wmv;*.m4a;*.mp3;*.wav;*.aac;*.flac;*.ogg;*.opus;*.wma|所有文件|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [System.IO.File]::WriteAllLines($env:V2T_PICK_OUT, $dialog.FileNames, (New-Object System.Text.UTF8Encoding($false)))
}
"""

_WIN_FOLDER_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择视频所在文件夹'
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [System.IO.File]::WriteAllText($env:V2T_PICK_OUT, $dialog.SelectedPath, (New-Object System.Text.UTF8Encoding($false)))
}
"""


def _run_powershell(script: str) -> str:
    with tempfile.TemporaryDirectory(prefix="v2t-pick-") as tmp:
        script_path = Path(tmp) / "pick.ps1"
        out_path = Path(tmp) / "selected.txt"
        script_path.write_text(script, encoding="utf-8-sig")
        env = os.environ.copy()
        env["V2T_PICK_OUT"] = str(out_path)
        args = ["-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
        try:
            r = subprocess.run(
                ["powershell", *args], capture_output=True, text=True,
                timeout=600, env=env,
            )
        except FileNotFoundError:
            try:
                r = subprocess.run(
                    ["pwsh", *args], capture_output=True, text=True,
                    timeout=600, env=env,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DialogError(f"无法打开系统选择框：{exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise DialogError(f"系统选择框超时：{exc}") from exc
        if out_path.exists():
            return out_path.read_text(encoding="utf-8")
        if r.returncode != 0:
            raise DialogError(f"系统选择框出错：{(r.stderr or '').strip()[-300:]}")
        return ""


def _pick_files_windows() -> list[Path]:
    return _existing(_run_powershell(_WIN_FILE_SCRIPT).splitlines())


def _pick_folder_windows() -> Path | None:
    folders = _existing([_run_powershell(_WIN_FOLDER_SCRIPT).strip()])
    return folders[0] if folders else None


# ------------------------------------------------------------------- Linux

def _pick_files_linux() -> list[Path]:
    if not shutil_which("zenity"):
        if shutil_which("kdialog"):
            r = subprocess.run(
                ["kdialog", "--getopenfilename", ".", "视频和音频 (*.mp4 *.mov *.mkv *.webm *.avi *.m4a *.mp3 *.wav)", "--multiple", "--separate-output"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                return _existing(r.stdout.splitlines())
            return []
        raise DialogError("没有可用的系统文件选择框，请直接粘贴文件路径")
    r = subprocess.run(
        ["zenity", "--file-selection", "--multiple", "--separator=\n",
         "--title=选择视频或音频文件"],
        capture_output=True, text=True,
    )  # a literal newline separator, not the two characters \\n
    if r.returncode == 0:
        return _existing(r.stdout.splitlines())
    return []


def _pick_folder_linux() -> Path | None:
    if shutil_which("zenity"):
        r = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=选择视频所在文件夹"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return _existing([r.stdout.strip()])[0] if r.stdout.strip() else None
        return None
    if shutil_which("kdialog"):
        r = subprocess.run(
            ["kdialog", "--getexistingdirectory", "."],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            found = _existing([r.stdout.strip()])
            return found[0] if found else None
        return None
    raise DialogError("没有可用的系统文件夹选择框，请直接粘贴文件夹路径")


def shutil_which(name: str) -> str | None:
    from shutil import which
    return which(name)
