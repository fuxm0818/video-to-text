import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_to_text import config, core  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_valid_filters_formats_and_clamps_workers(self):
        out = config._valid({
            "formats": ["md", "pdf", "docx"],
            "audio_format": "wav",
            "workers": 99,
        })
        self.assertEqual(out["formats"], ["md", "docx"])
        self.assertEqual(out["audio_format"], "wav")
        self.assertEqual(out["workers"], 4)
        self.assertEqual(config._valid({"workers": 0})["workers"], 1)

    def test_no_output_falls_back_to_markdown(self):
        out = config._valid({"formats": [], "audio_format": "none"})
        self.assertEqual(out["formats"], ["md"])

    def test_unknown_values_keep_defaults(self):
        out = config._valid({"audio_format": "flac", "formats": ["txt"]})
        self.assertIn(out["audio_format"], core.AUDIO_FORMATS)
        self.assertEqual(out["formats"], [])

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "config_dir", lambda: Path(tmp)):
                saved = config.save_settings({
                    "output_dir": str(Path(tmp) / "out"),
                    "formats": ["md"],
                    "audio_format": "none",
                    "workers": 2,
                })
                loaded = config.load_settings()
                self.assertEqual(saved, loaded)
                self.assertEqual(loaded["formats"], ["md"])
                self.assertEqual(loaded["audio_format"], "none")

    def test_broken_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("{not json", encoding="utf-8")
            with mock.patch.object(config, "config_dir", lambda: Path(tmp)):
                loaded = config.load_settings()
            self.assertEqual(loaded, config.defaults())

    def test_save_uses_validated_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "config_dir", lambda: Path(tmp)):
                config.save_settings({"formats": ["docx"], "workers": 9})
                data = json.loads((Path(tmp) / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(data["formats"], ["docx"])
            self.assertEqual(data["workers"], 4)


if __name__ == "__main__":
    unittest.main()
