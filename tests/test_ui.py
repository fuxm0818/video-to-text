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

    from video_to_text import config
    from video_to_text.gui import MainWindow

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
        models = mock.patch("video_to_text.gui.core.models_cached", return_value=True)
        models.start()
        self.addCleanup(models.stop)
        self.window = MainWindow(output_dir=str(self.out))
        self.window._refresh_timer.stop()

    def tearDown(self):
        thread = self.window._model_thread
        if thread is not None:
            thread.join(timeout=3)
        self.window.manager.shutdown()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _add_media(self, count: int = 2) -> list[Path]:
        paths = []
        for index in range(count):
            path = self.media / f"clip{index}.mp4"
            path.write_bytes(b"\x00" * 64)
            paths.append(path)
        with mock.patch("video_to_text.jobs.core.probe_duration", return_value=0):
            added, _ = self.window.manager.add_paths(
                [str(p) for p in paths], self.out
            )
        self.assertEqual(added, count)
        self.window._refresh(force=True)
        return paths

    def test_initial_state(self):
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertEqual(self.window.table.topLevelItemCount(), 0)
        self.assertIs(self.window.table_stack.currentWidget(), self.window.empty_page)
        self.assertTrue(self.window.output_dir_edit.isReadOnly())

    def test_add_files_populates_table(self):
        self._add_media(2)
        self.assertEqual(self.window.table.topLevelItemCount(), 2)
        self.assertIs(self.window.table_stack.currentWidget(), self.window.table)
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertEqual(self.window.file_count.text(), "2 个文件")

    def test_requires_some_output(self):
        self._add_media(1)
        self.window.fmt_md.setChecked(False)
        self.window.fmt_docx.setChecked(False)
        self.window.audio_combo.setCurrentIndex(
            self.window.audio_combo.findData("none")
        )
        self.assertFalse(self.window._settings_valid())
        self.assertFalse(self.window.start_button.isEnabled())
        self.window.audio_combo.setCurrentIndex(
            self.window.audio_combo.findData("m4a")
        )
        self.assertTrue(self.window.start_button.isEnabled())

    def test_remove_selected_row(self):
        self._add_media(2)
        self.window.table.selectAll()
        self.window._remove_selected()
        self.assertEqual(self.window.table.topLevelItemCount(), 0)
        self.assertIs(self.window.table_stack.currentWidget(), self.window.empty_page)

    def test_settings_persist(self):
        self.window.fmt_docx.setChecked(False)
        settings = config.load_settings()
        self.assertEqual(settings["formats"], ["md"])
        self.window.fmt_docx.setChecked(True)


if __name__ == "__main__":
    unittest.main()
