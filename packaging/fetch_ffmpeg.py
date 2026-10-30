#!/usr/bin/env python3
"""Download a static ffmpeg binary for the current platform from PyPI.

The binary comes from the imageio-ffmpeg wheel, which ships a self-contained
FFmpeg build for macOS (arm64/x86_64) and Windows x64. It is invoked as a
subprocess, so it is an aggregated work rather than a linked library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.7.0"
ROOT = Path(__file__).resolve().parent
DEST_DIR = ROOT / "ffmpeg"


def wheel_tag() -> str:
    if sys.platform == "darwin":
        return "macosx_11_0_arm64" if platform.machine() == "arm64" else "macosx_10_9_x86_64"
    if sys.platform == "win32":
        return "win_amd64"
    raise SystemExit("只支持 macOS 与 Windows；其他平台请自行安装 ffmpeg。")


def find_wheel() -> tuple[str, str, str]:
    url = f"https://pypi.org/pypi/imageio-ffmpeg/{VERSION}/json"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.load(resp)
    tag = wheel_tag()
    for item in data.get("urls", []):
        name = item.get("filename", "")
        if name.endswith(".whl") and tag in name:
            digest = (item.get("digests") or {}).get("sha256")
            if not digest:
                raise SystemExit(f"PyPI 没有提供 {name} 的 SHA-256，拒绝未校验下载")
            return item["url"], name, digest
    raise SystemExit(f"imageio-ffmpeg {VERSION} 没有 {tag} 的 wheel")


def download(url: str, dest: Path, sha256: str) -> None:
    mirrors = [url]
    if url.startswith("https://files.pythonhosted.org/"):
        mirrors.append(url.replace("https://files.pythonhosted.org/",
                                   "https://pypi.tuna.tsinghua.edu.cn/"))
    last: Exception | None = None
    for candidate in mirrors:
        try:
            print(f"下载 {candidate}")
            digest = hashlib.sha256()
            with urllib.request.urlopen(candidate, timeout=180) as resp, dest.open("wb") as fh:
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    digest.update(block)
                    fh.write(block)
            if digest.hexdigest() != sha256:
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"SHA-256 不匹配（期望 {sha256}，实际 {digest.hexdigest()}）"
                )
            return
        except Exception as exc:  # SSL resets are common on some networks
            last = exc
            print(f"失败：{exc}")
    raise SystemExit(f"下载失败：{last}")


def extract(wheel: Path, dest: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        members = [n for n in zf.namelist() if "/binaries/ffmpeg" in n and not n.endswith("/")]
        if not members:
            raise SystemExit("wheel 中没有 ffmpeg 可执行文件")
        with zf.open(members[0]) as src, dest.open("wb") as out:
            while True:
                block = src.read(1 << 20)
                if not block:
                    break
                out.write(block)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = parser.parse_args()

    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    dest = DEST_DIR / exe
    if dest.is_file() and not args.force:
        print(f"已存在：{dest}")
        return 0

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    url, name, sha256 = find_wheel()
    with tempfile.TemporaryDirectory(prefix="v2t-ffmpeg-") as tmp:
        wheel = Path(tmp) / name
        download(url, wheel, sha256)
        extract(wheel, dest)

    if sys.platform != "win32":
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    result = subprocess.run([str(dest), "-version"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[:500], file=sys.stderr)
        return 1
    print(f"ffmpeg 就绪：{dest}")
    print(result.stdout.splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
