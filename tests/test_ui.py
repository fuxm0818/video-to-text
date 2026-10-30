import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from video_to_text import config, styles
    from video_to_text.gui import MainWindow
    from video_to_text.gui.prefs import TAB_FORMAT

    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 未安装")
class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_tmp = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(
            QSettings.IniFormat, QSettings.UserScope, cls.settings_tmp.name
        )

    @classmethod
    def tearDownClass(cls):
        cls.settings_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patcher = mock.patch.object(config, "config_dir", lambda: root / "config")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.out = root / "out"
        self.out.mkdir()
        self.media = root / "media"
        self.media.mkdir()
        probe = mock.patch("video_to_text.jobs.core.probe_duration", return_value=0)
        probe.start()
        self.addCleanup(probe.stop)
        self.window = MainWindow(output_dir=str(self.out))
        self.window._refresh_timer.stop()

    def tearDown(self):
        prefs = self.window._prefs
        if prefs is not None:
            prefs.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _add_media(self, count: int = 2) -> list[Path]:
        paths = []
        for index in range(count):
            path = self.media / f"clip{index}.mp4"
            path.write_bytes(b"\x00" * 64)
            paths.append(path)
        self.window._add_paths([str(p) for p in paths])
        self.window._flash_message = ""
        self.window._refresh(force=True)
        return paths

    def _write_markdown(self, path: Path) -> None:
        (self.out / f"{path.stem}.md").write_text(
            f"- 源文件：`{path.resolve()}`\n\n# {path.stem}\n", encoding="utf-8"
        )

    def test_initial_state(self):
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertEqual(self.window.table.topLevelItemCount(), 0)
        self.assertIs(
            self.window.content.stack.currentWidget(), self.window.empty_page
        )
        self.assertEqual(self.window.status.summary.full_text(), "拖入文件开始")
        self.assertEqual(self.window.sidebar.current_filter(), "all")

    def test_add_files_populates_table(self):
        self._add_media(2)
        self.assertEqual(self.window.table.topLevelItemCount(), 2)
        self.assertIs(self.window.content.stack.currentWidget(), self.window.table)
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertEqual(self.window._counts["all"], 2)
        self.assertEqual(self.window._counts["queued"], 2)

    def test_filter_switches_to_empty_state(self):
        self._add_media(1)
        self.window.sidebar.set_filter("failed")
        self.window._refresh(force=True)
        self.assertIs(
            self.window.content.stack.currentWidget(), self.window.empty_page
        )
        self.assertEqual(self.window.empty_title.text(), "这个筛选下没有文件")
        self.window.sidebar.set_filter("all")
        self.window._refresh(force=True)
        self.assertIs(self.window.content.stack.currentWidget(), self.window.table)

    def test_remove_selected_row(self):
        self._add_media(2)
        self.window.table.selectAll()
        self.window._remove_selected()
        self.window._refresh(force=True)
        self.assertEqual(self.window.table.topLevelItemCount(), 0)
        self.assertIs(
            self.window.content.stack.currentWidget(), self.window.empty_page
        )

    def test_preferences_persist_immediately(self):
        self.window._open_prefs(TAB_FORMAT)
        prefs = self.window._prefs
        prefs.fmt_docx.setChecked(False)
        self.assertEqual(config.load_settings()["formats"], ["md"])
        self.assertEqual(self.window.settings["formats"], ["md"])
        prefs.fmt_docx.setChecked(True)
        self.assertEqual(config.load_settings()["formats"], ["md", "docx"])

    def test_preferences_keep_one_output(self):
        self.window._open_prefs(TAB_FORMAT)
        prefs = self.window._prefs
        prefs.fmt_md.setChecked(False)
        prefs.fmt_docx.setChecked(False)
        prefs.audio_combo.setCurrentIndex(prefs.audio_combo.findData("none"))
        self.assertFalse(prefs._valid())
        prefs.close()
        self.assertEqual(config.load_settings()["formats"], ["md"])

    def test_existing_outputs_are_skipped(self):
        paths = self._add_media(2)
        for path in paths:
            self._write_markdown(path)
        self.window.settings["formats"] = ["md"]
        self.window.settings["audio_format"] = "none"
        self.window._apply_settings_ui()
        self.window._start_job()
        self.window._refresh(force=True)
        self.assertEqual(self.window._job["state"], "done")
        self.assertEqual(self.window._job["skipped"], 2)
        self.assertEqual(self.window._counts["skipped"], 2)

    def test_styles_build_for_both_schemes(self):
        for dark in (False, True):
            css = styles.build(dark)
            self.assertNotIn("%", css)
            self.assertGreater(len(css), 2000)


if __name__ == "__main__":
    unittest.main()
