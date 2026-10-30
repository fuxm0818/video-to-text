"""Small persisted preferences (output folder, formats, concurrency)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import core


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "VideoToText"


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return base / "Video to Text"


def defaults() -> dict:
    return {
        "output_dir": str(default_output_dir()),
        "formats": ["md", "docx"],
        "audio_format": "m4a",
        "workers": core.default_workers(),
        "force": False,
    }


def _valid(data: dict) -> dict:
    base = defaults()
    out = dict(base)
    if isinstance(data.get("output_dir"), str) and data["output_dir"].strip():
        out["output_dir"] = str(Path(data["output_dir"]).expanduser())
    formats = data.get("formats")
    if isinstance(formats, list):
        chosen = [f for f in formats if f in core.TEXT_FORMATS]
        out["formats"] = chosen
    if data.get("audio_format") in core.AUDIO_FORMATS:
        out["audio_format"] = data["audio_format"]
    try:
        workers = int(data.get("workers", base["workers"]))
        out["workers"] = max(1, min(4, workers))
    except (TypeError, ValueError):
        pass
    out["force"] = data.get("force") is True
    if not out["formats"] and out["audio_format"] == "none":
        out["formats"] = ["md"]
    return out


def load_settings() -> dict:
    path = config_dir() / "settings.json"
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return _valid(data if isinstance(data, dict) else {})
    except (OSError, ValueError):
        return defaults()


def save_settings(data: dict) -> dict:
    out = _valid(data)
    try:
        path = config_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return out
