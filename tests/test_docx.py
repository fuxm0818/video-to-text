import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_to_text import core, docx  # noqa: E402


def sample_transcript() -> core.Transcript:
    return core.Transcript(
        source=Path("/tmp/演示 & <测试>.mp4"),
        title="演示 & <测试>",
        duration=30.0,
        segments=[core.Segment(0.0, 5.0, "第一句。"), core.Segment(5.0, 12.0, "第二句！")],
        cover=12.0,
        audio_name="演示.m4a",
    )


class DocxTests(unittest.TestCase):
    def test_contains_required_parts_and_escapes_xml(self):
        t = sample_transcript()
        data = docx.build_docx(core.docx_blocks(t), t.title)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("word/document.xml", names)
            self.assertIn("word/styles.xml", names)
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("数据来源与局限", xml)
        self.assertIn("未经人工校对", xml)
        self.assertIn("00:00", xml)
        self.assertIn("演示 &amp; &lt;测试&gt;", xml)
        self.assertNotIn("<测试>", xml)
        self.assertNotIn("OCR", xml)

    def test_write_docx_creates_readable_file(self):
        t = sample_transcript()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "演示.docx"
            docx.write_docx(path, core.docx_blocks(t), t.title)
            self.assertGreater(path.stat().st_size, 1000)
            with zipfile.ZipFile(path) as zf:
                self.assertIsNone(zf.testzip())

    def test_blocks_include_timeline_paragraphs_and_limitations(self):
        blocks = core.docx_blocks(sample_transcript())
        kinds = [kind for kind, _ in blocks]
        self.assertEqual(kinds[0], "title")
        self.assertIn(("h2", "带时间轴文稿"), blocks)
        self.assertIn(("h2", "连续文稿"), blocks)
        self.assertIn(("h2", "数据来源与局限"), blocks)
        self.assertIn(("meta", "音频导出：演示.m4a"), blocks)


if __name__ == "__main__":
    unittest.main()
