import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_to_text import core  # noqa: E402


class ProbeFallbackTests(unittest.TestCase):
    """The packaged app ships ffmpeg but no ffprobe."""

    def _fake_run(self, stdout="", stderr="", code=0):
        return lambda cmd, timeout=None: subprocess.CompletedProcess(cmd, code, stdout, stderr)

    def test_duration_from_ffmpeg_stderr(self):
        err = "Input #0, mov,mp4\n  Duration: 00:01:23.50, start: 0.000, bitrate: 128 kb/s\n"
        with mock.patch.object(core, "tool_path", lambda name: None if name == "ffprobe" else "/ffmpeg"), \
                mock.patch.object(core, "run", self._fake_run(stderr=err, code=1)):
            self.assertAlmostEqual(core.probe_duration("clip.mp4"), 83.5)

    def test_duration_missing_returns_zero(self):
        with mock.patch.object(core, "tool_path", lambda name: None if name == "ffprobe" else "/ffmpeg"), \
                mock.patch.object(core, "run", self._fake_run(stderr="no media")):
            self.assertEqual(core.probe_duration("clip.mp4"), 0.0)

    def test_duration_prefers_ffprobe(self):
        with mock.patch.object(core, "tool_path", lambda name: "/ffprobe"), \
                mock.patch.object(core, "run", self._fake_run(stdout="12.5\n")):
            self.assertAlmostEqual(core.probe_duration("clip.mp4"), 12.5)

    def test_duration_bad_ffprobe_output(self):
        with mock.patch.object(core, "tool_path", lambda name: "/ffprobe"), \
                mock.patch.object(core, "run", self._fake_run(stdout="N/A\n")):
            self.assertEqual(core.probe_duration("clip.mp4"), 0.0)

    def test_audio_codec_from_ffmpeg_stderr(self):
        err = "  Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo\n"
        with mock.patch.object(core, "tool_path", lambda name: None if name == "ffprobe" else "/ffmpeg"), \
                mock.patch.object(core, "run", self._fake_run(stderr=err, code=1)):
            self.assertEqual(core.probe_audio_codec("clip.mp4"), "aac")

    def test_audio_codec_absent(self):
        err = "  Stream #0:0: Video: h264, yuv420p, 1280x720\n"
        with mock.patch.object(core, "tool_path", lambda name: None if name == "ffprobe" else "/ffmpeg"), \
                mock.patch.object(core, "run", self._fake_run(stderr=err, code=1)):
            self.assertIsNone(core.probe_audio_codec("clip.mp4"))


class FakePuncModel:
    punc_model = object()
    punc_kwargs = {}

    def inference(self, text, model=None, kwargs=None):
        return [{"text": text.replace("大家好", "大家好。") + "！"}]


class SentenceTests(unittest.TestCase):
    def test_splits_on_model_punctuation_and_keeps_time_order(self):
        chunks = [
            core.Segment(0.0, 2.0, "大家好。今天"),
            core.Segment(2.0, 4.0, "我们讲三个问题！"),
        ]
        out = core.sentences_from(chunks, FakePuncModel())
        self.assertEqual([s.text for s in out], ["大家好。", "今天我们讲三个问题！"])
        self.assertGreaterEqual(out[1].start, out[0].start)
        self.assertLessEqual(out[-1].end, 4.0)

    def test_without_punc_model_text_stays_one_segment(self):
        chunks = [core.Segment(0.0, 2.0, "大家好。"), core.Segment(2.0, 4.0, "再见！")]
        out = core.sentences_from(chunks, None)
        self.assertEqual([s.text for s in out], ["大家好再见"])
        self.assertEqual(out[0].start, 0.0)
        self.assertEqual(out[0].end, 4.0)

    def test_empty_input(self):
        self.assertEqual(core.sentences_from([], None), [])
        self.assertEqual(core.sentences_from([core.Segment(0, 1, "  ")], None), [])

    def test_paragraphs_respect_min_len(self):
        segs = [core.Segment(0, 1, "第一句。"), core.Segment(1, 2, "第二句。")]
        self.assertEqual(core.paragraphs(segs, min_len=1), ["第一句。", "第二句。"])
        self.assertEqual(core.paragraphs(segs), ["第一句。第二句。"])


class StemAndCollectionTests(unittest.TestCase):
    def test_sanitize_stem(self):
        self.assertEqual(core.sanitize_stem('  a/b:c*?"<>|  '), "a_b_c______")
        self.assertEqual(core.sanitize_stem("   "), "video")
        self.assertEqual(len(core.sanitize_stem("x" * 200)), core.MAX_STEM)

    def test_assign_stems_reuses_same_source_and_renames_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            src = root / "讲座.mp4"
            src.write_bytes(b"x")
            other = root / "别的讲座.mp4"
            other.write_bytes(b"x")
            (out / "讲座.md").write_text(
                f"# 讲座\n\n- 源文件：`{src.resolve()}`\n", encoding="utf-8"
            )
            stems = core.assign_stems([src], out)
            self.assertEqual(stems[str(src.resolve())], "讲座")

            (out / "讲座.md").write_text(
                f"# 讲座\n\n- 源文件：`{other.resolve()}`\n", encoding="utf-8"
            )
            stems = core.assign_stems([src], out)
            self.assertEqual(stems[str(src.resolve())], "讲座 (2)")

    def test_collect_media_filters_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.mp4").write_bytes(b"x")
            (root / "a.MP3").write_bytes(b"x")
            (root / "notes.txt").write_text("x", encoding="utf-8")
            sub = root / "sub"
            sub.mkdir()
            (sub / "c.mov").write_bytes(b"x")
            files = core.collect_media([root])
            self.assertEqual([p.name for p in files], ["a.MP3", "b.mp4", "c.mov"])
            skipped = core.collect_media([root], skip_dirs=[sub])
            self.assertEqual([p.name for p in skipped], ["a.MP3", "b.mp4"])
            with self.assertRaises(core.TranscriptionError):
                core.collect_media([root / "missing.mp4"])


class MarkdownTests(unittest.TestCase):
    def _transcript(self):
        return core.Transcript(
            source=Path("/tmp/示例.mp4"),
            title="示例",
            duration=10.0,
            segments=[core.Segment(0.0, 3.0, "第一句。"), core.Segment(3.0, 8.0, "第二句！")],
            cover=8.0,
            audio_name="示例.m4a",
        )

    def test_roundtrip(self):
        t = self._transcript()
        text = core.render_markdown(t)
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "示例.md"
            md.write_text(text, encoding="utf-8")
            parsed = core.parse_markdown(md)
            self.assertEqual(parsed.title, "示例")
            self.assertEqual(parsed.duration, 10.0)
            self.assertEqual(parsed.audio_name, "示例.m4a")
            self.assertEqual([s.text for s in parsed.segments], ["第一句。", "第二句！"])
            self.assertEqual(core.markdown_source(md), str(Path("/tmp/示例.mp4").resolve()))

    def test_limitations_are_honest_and_mention_no_ocr(self):
        text = core.render_markdown(self._transcript())
        self.assertIn("未经人工校对", text)
        self.assertIn("专有名词与同音字可能出错", text)
        self.assertIn("80%", text)
        self.assertNotIn("OCR", text)
        self.assertNotIn("ocr", text.lower())

    def test_ratio_clamped(self):
        t = self._transcript()
        t.cover = 999
        self.assertEqual(t.ratio, 1.0)
        t.duration = 0
        self.assertEqual(t.ratio, 0.0)

    def test_timestamps(self):
        self.assertEqual(core.fmt_ts(0), "00:00")
        self.assertEqual(core.fmt_ts(3661.4), "01:01:01")
        self.assertEqual(core.parse_ts("01:02:03"), 3723)
        self.assertEqual(core.parse_ts("02:03"), 123)


if __name__ == "__main__":
    unittest.main()
