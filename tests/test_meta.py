import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_to_text import __version__  # noqa: E402


class MetadataTests(unittest.TestCase):
    def test_package_version_matches_pyproject(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
