import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_to_text import jobs  # noqa: E402
from video_to_text.jobs import JobManager, Task  # noqa: E402


class TaskTests(unittest.TestCase):
    def test_to_dict_exposes_cover_and_error_detail(self):
        task = Task(id="abc", path=Path("/tmp/a.mp4"), size=10)
        task.cover = 95.5
        task.error_detail = "Traceback ..."
        data = task.to_dict()
        self.assertEqual(data["cover"], 95.5)
        self.assertEqual(data["error_detail"], "Traceback ...")
        self.assertEqual(data["name"], "a.mp4")
        self.assertEqual(data["stage_label"], "")


class ModelCacheTests(unittest.TestCase):
    def test_counts_bytes_in_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "models" / "paraformer"
            nested.mkdir(parents=True)
            (nested / "model.bin").write_bytes(b"x" * 2048)
            with mock.patch.dict(os.environ, {"MODELSCOPE_CACHE": tmp}):
                self.assertEqual(jobs.model_cache_dir(), Path(tmp))
                self.assertGreaterEqual(jobs.model_cache_bytes(), 2048)

    def test_missing_cache_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope"
            with mock.patch.dict(os.environ, {"MODELSCOPE_CACHE": str(missing)}):
                self.assertEqual(jobs.model_cache_bytes(), 0)


class JobManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.out = root / "out"
        self.out.mkdir()
        self.manager = JobManager()
        self.addCleanup(self.manager.shutdown)
        self.probe = mock.patch.object(jobs.core, "probe_duration", return_value=0)
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.media = root / "media"
        self.media.mkdir()

    def _add(self, *names: str) -> list[str]:
        paths = []
        for name in names:
            path = self.media / name
            path.write_bytes(b"\x00" * 32)
            paths.append(str(path))
        added, _ = self.manager.add_paths(paths, self.out)
        self.assertEqual(added, len(paths))
        return paths

    def _write_markdown(self, path: str) -> None:
        stem = Path(path).stem
        (self.out / f"{stem}.md").write_text(
            f"- 源文件：`{Path(path).resolve()}`\n\n# {stem}\n", encoding="utf-8"
        )

    def test_queue_edits_rejected_while_running(self):
        self._add("a.mp4")
        with self.manager._lock:
            self.manager._job["running"] = True
        try:
            with self.assertRaises(RuntimeError):
                self.manager.add_paths([str(self.media)], self.out)
            task_id = self.manager.snapshot()["tasks"][0]["id"]
            with self.assertRaises(RuntimeError):
                self.manager.remove(task_id)
            with self.assertRaises(RuntimeError):
                self.manager.clear()
        finally:
            with self.manager._lock:
                self.manager._job["running"] = False

    def test_start_only_ids_skips_existing_outputs(self):
        first, second = self._add("a.mp4", "b.mp4")
        self._write_markdown(second)
        task_id = self.manager.snapshot()["tasks"][1]["id"]
        self.manager.start(
            self.out, ["md"], "none", 1, False, only_ids=[task_id]
        )
        snapshot = self.manager.snapshot()
        self.assertFalse(snapshot["job"]["running"])
        self.assertEqual(snapshot["job"]["state"], "done")
        self.assertEqual(snapshot["job"]["total"], 1)
        self.assertEqual(snapshot["job"]["skipped"], 1)
        self.assertEqual(
            [task["status"] for task in snapshot["tasks"]], ["queued", "skipped"]
        )
        self.assertEqual(snapshot["tasks"][1]["outputs"], {"md": "b.md"})

    def test_start_requires_some_output(self):
        self._add("a.mp4")
        with self.assertRaises(RuntimeError):
            self.manager.start(self.out, [], "none", 1, False)

    def test_start_rejects_second_run(self):
        self._add("a.mp4")
        self._write_markdown(str(self.media / "a.mp4"))
        self.manager.start(self.out, ["md"], "none", 1, False)
        with self.manager._lock:
            self.manager._job["running"] = True
        try:
            with self.assertRaises(RuntimeError):
                self.manager.start(self.out, ["md"], "none", 1, False)
        finally:
            with self.manager._lock:
                self.manager._job["running"] = False


if __name__ == "__main__":
    unittest.main()
