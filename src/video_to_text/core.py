"""Transcription core: ffmpeg audio extraction, FunASR, Markdown/DOCX output.

The heavy imports (torch, funasr, modelscope) are deliberately lazy so the
desktop window starts instantly and tests can run without the ASR stack.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

MEDIA_EXT = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".flv", ".wmv",
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma",
}
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma"}
TEXT_FORMATS = {"md", "docx"}
AUDIO_FORMATS = {"m4a", "wav", "none"}
SENT_END = "。！？!?"

MODEL_IDS = (
    "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
)

MAX_FILES = 2000
MAX_STEM = 80


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    source: Path
    title: str
    duration: float
    segments: list[Segment]
    elapsed: float = 0.0
    cover: float = 0.0
    audio_name: str = ""
    reused: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.duration <= 0:
            return 0.0
        return min(1.0, max(0.0, self.cover / self.duration))

    @property
    def paragraphs(self) -> list[str]:
        return paragraphs(self.segments)


# ---------------------------------------------------------------- tool lookup

def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _platform_tool_name(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def _candidates(name: str) -> list[Path]:
    exe = _platform_tool_name(name)
    out: list[Path] = []
    env_dir = os.environ.get("V2T_FFMPEG_DIR")
    if env_dir:
        out.append(Path(env_dir) / exe)
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        out += [base / exe, Path(sys.executable).parent / exe]
    out.append(_project_root() / "packaging" / "ffmpeg" / exe)
    return out


def tool_path(name: str) -> str | None:
    """Return an absolute ffmpeg/ffprobe path, preferring the bundled copy."""
    env_key = "V2T_" + name.upper()
    explicit = os.environ.get(env_key)
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise TranscriptionError(f"{env_key} 指向的文件不存在：{explicit}")
    for path in _candidates(name):
        if path.is_file():
            if sys.platform != "win32":
                try:
                    path.chmod(path.stat().st_mode | 0o111)
                except OSError:
                    pass
            return str(path)
    found = shutil.which(name)
    return found


def require_tool(name: str) -> str:
    path = tool_path(name)
    if not path:
        raise TranscriptionError(
            f"找不到 {name}。请安装 ffmpeg（macOS: brew install ffmpeg；"
            "Windows: winget install Gyan.FFmpeg），或把它放到程序目录。"
        )
    return path


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    # ffmpeg prints UTF-8; decoding with the Windows ANSI code page can raise
    # UnicodeDecodeError on Chinese paths.
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )


# -------------------------------------------------------------------- probing

_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_FFMPEG_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:\s*([A-Za-z0-9_]+)")


def _ffmpeg_info(path: str | Path) -> str:
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        return ""
    r = run([ffmpeg, "-nostdin", "-hide_banner", "-i", str(path)])
    return r.stderr or ""


def probe_duration(path: str | Path) -> float:
    ffprobe = tool_path("ffprobe")
    if ffprobe:
        r = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
        try:
            return max(0.0, float(r.stdout.strip()))
        except ValueError:
            return 0.0
    match = _FFMPEG_DURATION_RE.search(_ffmpeg_info(path))
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))


def probe_audio_codec(path: str | Path) -> str | None:
    ffprobe = tool_path("ffprobe")
    if ffprobe:
        r = run([ffprobe, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_name",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
        codec = r.stdout.strip().splitlines()
        return codec[0].strip() if codec else None
    match = _FFMPEG_AUDIO_RE.search(_ffmpeg_info(path))
    return match.group(1) if match else None


def fmt_ts(seconds: float) -> str:
    seconds = int(round(max(0.0, seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_ts(text: str) -> float:
    parts = [int(x) for x in text.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[-3] * 3600 + parts[-2] * 60 + parts[-1]


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def natural_key(text: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def sanitize_stem(stem: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    stem = re.sub(r"\s+", " ", stem)
    if len(stem) > MAX_STEM:
        stem = stem[:MAX_STEM].rstrip(" .")
    return stem or "video"


# ---------------------------------------------------------------- collection

def collect_media(inputs: list[str | Path], skip_dirs: list[Path] | None = None) -> list[Path]:
    """Expand files/folders into a de-duplicated, naturally sorted media list."""
    skip = [p.resolve() for p in (skip_dirs or [])]
    found: dict[str, Path] = {}

    def allowed(path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for base in skip:
            if resolved == base or base in resolved.parents:
                return False
        return path.suffix.lower() in MEDIA_EXT and path.is_file()

    for item in inputs:
        path = Path(item).expanduser()
        if path.is_file():
            if allowed(path):
                found[str(path.resolve())] = path
        elif path.is_dir():
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(
                    (d for d in dirs if not d.startswith(".")),
                    key=natural_key,
                )
                for name in sorted(names, key=natural_key):
                    child = Path(root) / name
                    if allowed(child):
                        found[str(child.resolve())] = child
        else:
            raise TranscriptionError(f"路径不存在：{item}")
    files = sorted(found.values(), key=lambda p: natural_key(p.name))
    if len(files) > MAX_FILES:
        raise TranscriptionError(f"一次最多处理 {MAX_FILES} 个文件，当前选中 {len(files)} 个")
    return files


def assign_stems(paths: list[Path], outdir: Path) -> dict[str, str]:
    """Choose output basenames, reusing an existing transcript for the same source."""
    used: set[str] = set()
    result: dict[str, str] = {}
    for path in paths:
        base = sanitize_stem(path.stem)
        stem, n = base, 2
        while True:
            conflict = any(
                (outdir / f"{stem}{ext}").exists() for ext in (".md", ".docx", ".m4a", ".wav")
            )
            reuse = False
            md = outdir / f"{stem}.md"
            if conflict and md.exists():
                reuse = markdown_source(md) == str(path.resolve())
            if stem not in used and (not conflict or reuse):
                break
            stem = f"{base} ({n})"
            n += 1
        used.add(stem)
        result[str(path.resolve())] = stem
    return result


def markdown_source(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                m = re.match(r"^- 源文件：`(.+)`\s*$", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------- ASR engine

_MODEL = None


def load_model(log=None) -> object:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    if log:
        log("加载语音识别模型（首次约需 10–30 秒）")
    import torch
    torch.set_num_threads(int(os.environ.get("V2T_THREADS", "2")))
    from funasr import AutoModel
    _MODEL = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        disable_update=True,
        disable_pbar=True,
    )
    return _MODEL


def models_cached() -> bool:
    """Ask ModelScope itself, so every cache layout it supports is covered."""
    try:
        from modelscope.hub.snapshot_download import snapshot_download
        for repo in MODEL_IDS:
            snapshot_download(repo, local_files_only=True)
        return True
    except Exception:
        return False


def ensure_models(log=None) -> None:
    """Make sure all models are on disk before worker processes start.

    Running this once in a single process avoids several workers downloading
    the same ~2.1 GB into the same cache directory at the same time.
    """
    if models_cached():
        if log:
            log("语音模型已就绪")
        return
    if log:
        log("首次运行：准备语音模型（约 2.1 GB，只需下载一次）")
    from modelscope.hub.snapshot_download import snapshot_download
    for repo in MODEL_IDS:
        if log:
            log(f"下载模型 {repo.split('/')[-1]}")
        snapshot_download(repo)
    if log:
        log("语音模型准备完成")


def extract_audio(src: Path, wav: Path) -> None:
    ffmpeg = require_tool("ffmpeg")
    r = run([ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    if r.returncode != 0 or not wav.exists() or wav.stat().st_size <= 44:
        detail = (r.stderr or "").strip().splitlines()
        raise TranscriptionError(
            "抽取音轨失败" + ("：" + detail[-1] if detail else "（文件可能没有音轨）")
        )


def export_audio(src: Path, dst: Path, fmt: str) -> None:
    """Export the original audio track. AAC is stream-copied when possible."""
    if fmt not in {"m4a", "wav"}:
        return
    ffmpeg = require_tool("ffmpeg")
    codec = probe_audio_codec(src)
    if not codec:
        raise TranscriptionError("源文件没有音轨，无法导出音频")
    common = [ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-i", str(src),
              "-map", "0:a:0", "-vn"]
    if fmt == "wav":
        r = run(common + ["-c:a", "pcm_s16le", str(dst)])
        if r.returncode == 0 and dst.exists() and dst.stat().st_size > 44:
            return
        raise TranscriptionError("导出 WAV 失败：" + (r.stderr or "").strip()[-300:])

    if codec == "aac":
        r = run(common + ["-c:a", "copy", "-movflags", "+faststart", str(dst)])
        if r.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return
    r = run(common + ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)])
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        raise TranscriptionError("导出 M4A 失败：" + (r.stderr or "").strip()[-300:])


def _plain(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def _coalesce(segs: list[Segment]) -> list[Segment]:
    out: list[Segment] = []
    buf: list[Segment] = []
    for seg in segs:
        buf.append(seg)
        text = "".join(x.text for x in buf)
        if (seg.text and seg.text[-1] in SENT_END) or len(text) >= 24:
            out.append(Segment(buf[0].start, buf[-1].end, text.strip()))
            buf = []
    if buf:
        out.append(Segment(buf[0].start, buf[-1].end, "".join(x.text for x in buf).strip()))
    return out


def _parse_result(res, duration: float) -> list[Segment]:
    if not res:
        return []
    item = res[0] if isinstance(res, list) else res
    if not isinstance(item, dict):
        return []
    sentences = item.get("sentence_info")
    if sentences:
        return [
            Segment(s["start"] / 1000.0, s["end"] / 1000.0, re.sub(r"\s+", " ", s["text"]).strip())
            for s in sentences
            if _plain(s.get("text", ""))
        ]
    stamps = item.get("timestamp") or []
    text = re.sub(r"\s+", "", item.get("text", ""))
    if stamps and len(stamps) == len(text):
        return _coalesce([
            Segment(a / 1000.0, b / 1000.0, ch)
            for (a, b), ch in zip(stamps, text)
        ])
    return [Segment(0.0, duration, text)] if text else []


def asr_wav(wav: Path, log=None) -> list[Segment]:
    duration = probe_duration(wav)
    if duration < 0.5:
        raise TranscriptionError("音频近乎为空（不足 0.5 秒）")
    model = load_model(log)
    if log:
        log("语音识别中")
    try:
        res = model.generate(
            input=str(wav), batch_size_s=60, merge_vad=True,
            merge_length_s=15, sentence_timestamp=True,
        )
    except IndexError:
        raise TranscriptionError("没有检测到人声片段，未做语音识别")
    segs = _parse_result(res, duration)
    if not segs:
        # A few recordings decode to an empty result with merge_vad enabled.
        try:
            res = model.generate(
                input=str(wav), batch_size_s=60, merge_vad=False,
                sentence_timestamp=True,
            )
        except IndexError:
            raise TranscriptionError("没有检测到人声片段，未做语音识别")
        segs = _parse_result(res, duration)
    return segs


PUNC_CHUNK = 400
MAX_SENT_CHARS = 120


def _punc_text(model, text: str) -> str | None:
    if not text or model is None or getattr(model, "punc_model", None) is None:
        return None
    try:
        res = model.inference(text, model=model.punc_model, kwargs=model.punc_kwargs)
        if res and isinstance(res[0], dict):
            return re.sub(r"\s+", " ", res[0].get("text") or "").strip() or None
    except Exception:
        return None
    return None


def sentences_from(chunks: list[Segment], model) -> list[Segment]:
    """Re-punctuate the full text, then map sentences back onto timestamps."""
    chars: list[str] = []
    t0: list[float] = []
    t1: list[float] = []
    for seg in chunks:
        text = _plain(seg.text)
        if not text:
            continue
        n = len(text)
        a, b = seg.start, max(seg.end, seg.start)
        for k, ch in enumerate(text):
            chars.append(ch)
            t0.append(a + (b - a) * k / n)
            t1.append(a + (b - a) * (k + 1) / n)
    if not chars:
        return []

    text = "".join(chars)
    pieces: list[str] = []
    i = 0
    while i < len(text):
        part = text[i:i + PUNC_CHUNK]
        got = _punc_text(model, part)
        pieces.append(got if (got and _plain(got) == part) else part)
        i += len(part)

    sents: list[Segment] = []
    cur: list[str] = []
    start: float | None = None
    ci = 0
    for ch in "".join(pieces):
        if ch in SENT_END:
            cur.append(ch)
            if _plain("".join(cur)):
                sents.append(Segment(start or 0.0, t1[max(0, ci - 1)], "".join(cur).strip()))
            cur, start = [], None
            continue
        if ch in "，、；：,.!? \n“”" or not _plain(ch):
            if ch in "，；" and len(_plain("".join(cur))) >= MAX_SENT_CHARS:
                sents.append(Segment(start or 0.0, t1[max(0, ci - 1)], "".join(cur).strip()))
                cur, start = [], None
                continue
            cur.append(ch)
            continue
        if ci >= len(chars):
            break
        if start is None:
            start = t0[ci]
        cur.append(ch)
        ci += 1
    if _plain("".join(cur)):
        sents.append(Segment(start or 0.0, t1[max(0, ci - 1)], "".join(cur).strip()))
    return sents


def paragraphs(segs: list[Segment], min_len: int = 120) -> list[str]:
    out: list[str] = []
    buf = ""
    for seg in segs:
        buf += seg.text
        if len(buf) >= min_len and buf[-1:] in SENT_END:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


# ------------------------------------------------------------------ transcript

def transcribe_file(
    src: Path,
    formats: set[str],
    audio_format: str,
    outdir: Path,
    stem: str,
    force: bool = False,
    log=None,
    stage=None,
    temp_prefix: str = "v2t-",
) -> Transcript:
    """Transcribe one file and write requested outputs. Returns the result."""
    def note(message: str) -> None:
        if log:
            log(message)

    def phase(name: str) -> None:
        if stage:
            stage(name)

    if not formats and audio_format == "none":
        raise TranscriptionError("请至少选择一种输出内容（文稿或音频）")

    t0 = time.time()
    outdir.mkdir(parents=True, exist_ok=True)
    md_path = outdir / f"{stem}.md"
    docx_path = outdir / f"{stem}.docx"
    audio_path = outdir / (f"{stem}.m4a" if audio_format == "m4a" else f"{stem}.wav")

    need_text = bool(formats)
    transcript: Transcript | None = None
    reuse = need_text and (not force) and md_path.exists() and \
        markdown_source(md_path) == str(src.resolve())
    if reuse:
        note("发现同一文件的已有文稿，跳过语音识别")
        transcript = parse_markdown(md_path)
        transcript.reused = True
        # The old audio name may refer to a previous output; recompute below.
        transcript.audio_name = ""

    if need_text and transcript is None:
        phase("extract")
        note("抽取音轨")
        with tempfile.TemporaryDirectory(prefix=temp_prefix) as tmp:
            wav = Path(tmp) / "audio.wav"
            extract_audio(src, wav)
            phase("asr")
            chunks = asr_wav(wav, log)
            if not chunks:
                raise TranscriptionError("没有识别到语音内容（可能是纯音乐、静音或音轨异常）")
            phase("punctuate")
            model = load_model()
            segs = sentences_from(chunks, model)
        if not segs:
            raise TranscriptionError("没有识别到语音内容（可能是纯音乐、静音或音轨异常）")
        duration = probe_duration(src)
        transcript = Transcript(
            source=src,
            title=src.stem,
            duration=duration,
            segments=segs,
            elapsed=time.time() - t0,
            cover=sum(max(0.0, s.end - s.start) for s in segs),
        )
        note(f"识别完成：{len(segs)} 段，覆盖 {fmt_ts(transcript.cover)}")

    if transcript is None:
        transcript = Transcript(
            source=src, title=src.stem, duration=probe_duration(src), segments=[]
        )

    if audio_format != "none":
        phase("audio")
        if audio_path.exists() and not force:
            note("音频已存在，跳过导出")
            transcript.audio_name = audio_path.name
        else:
            note("导出音频")
            try:
                export_audio(src, audio_path, audio_format)
                transcript.audio_name = audio_path.name
            except TranscriptionError as exc:
                transcript.warnings.append(str(exc))
                note(str(exc))

    if "md" in formats:
        phase("write")
        if not (md_path.exists() and not force and transcript.reused):
            md_path.write_text(render_markdown(transcript), encoding="utf-8")
        note(f"写入 {md_path.name}")

    if "docx" in formats:
        phase("write")
        if not (docx_path.exists() and not force and transcript.reused):
            from .docx import write_docx
            write_docx(docx_path, docx_blocks(transcript), title=transcript.title)
        note(f"写入 {docx_path.name}")

    transcript.elapsed = time.time() - t0
    if not transcript.cover and transcript.segments:
        transcript.cover = sum(max(0.0, s.end - s.start) for s in transcript.segments)
    if audio_format != "none" and not transcript.audio_name and not formats:
        raise TranscriptionError("音频导出失败：" + "；".join(transcript.warnings))
    return transcript


def docx_blocks(t: Transcript) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = [
        ("title", t.title),
        ("meta", f"源文件：{t.source}"),
        ("meta", f"时长：{fmt_ts(t.duration)}（{t.duration:.1f} 秒）"),
        ("meta", f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"),
        ("meta", f"语音识别：{len(t.segments)} 段，覆盖 {t.cover:.0f} 秒（{t.ratio * 100:.0f}%）"),
    ]
    if t.audio_name:
        blocks.append(("meta", f"音频导出：{t.audio_name}"))
    blocks.append(("h2", "带时间轴文稿"))
    for seg in t.segments:
        blocks.append(("timestamp", f"[{fmt_ts(seg.start)}] {seg.text}"))
    blocks.append(("h2", "连续文稿"))
    for para in t.paragraphs:
        blocks.append(("body", para))
    blocks.append(("h2", "数据来源与局限"))
    for line in limitation_lines(t):
        blocks.append(("body", line))
    return blocks


def limitation_lines(t: Transcript) -> list[str]:
    lines = [
        "全文来自语音识别（FunASR paraformer-zh + fsmn-vad 分段 + ct-punc 断句标点），"
        "未经人工校对，专有名词与同音字可能出错。",
        "只识别音轨中的语音，不识别画面上的文字；语速过快、多人抢话、背景噪声大时可能漏识别。",
        f"识别覆盖 {t.cover:.0f} 秒 / 音频 {t.duration:.0f} 秒（{t.ratio * 100:.0f}%）；"
        "未覆盖的部分是未检测到人声的片段。",
        "所有处理都在本机完成，文件不会上传到任何服务器。",
    ]
    for warning in t.warnings:
        lines.append(f"本次运行提示：{warning}")
    return lines


def render_markdown(t: Transcript) -> str:
    out = [f"# {t.title}", ""]
    out += [f"- 源文件：`{t.source.resolve()}`"]
    out += [f"- 时长：{fmt_ts(t.duration)}（{t.duration:.1f} 秒）"]
    out += [f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"]
    out += [f"- 语音识别（ASR）：{len(t.segments)} 段，覆盖 {t.cover:.0f} 秒（{t.ratio * 100:.0f}%）"]
    if t.audio_name:
        out += [f"- 音频导出：`{t.audio_name}`"]
    for warning in t.warnings:
        out += [f"- 提示：{warning}"]
    out += ["", "## 带时间轴文稿", ""]
    for seg in t.segments:
        out += [f"- `{fmt_ts(seg.start)}` {seg.text}"]
    out += ["", "## 连续文稿", ""]
    for para in t.paragraphs:
        out += [para, ""]
    out += ["## 数据来源与局限", ""]
    for line in limitation_lines(t):
        out += [f"- {line}"]
    out += [""]
    return "\n".join(out)


_SOURCE_RE = re.compile(r"^- 源文件：`(.+)`\s*$")
_DURATION_RE = re.compile(r"^- 时长：(.+?)（([\d.]+) 秒）")
_ASR_RE = re.compile(r"^- 语音识别（ASR）：(\d+) 段，覆盖 (\d+) 秒")
_AUDIO_RE = re.compile(r"^- 音频导出：`(.+)`")
_TIMELINE_RE = re.compile(r"^- `([\d:]+)`\s?(.*)$")


def parse_markdown(path: Path) -> Transcript:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = path.stem
    source = path
    duration = 0.0
    cover = 0.0
    audio_name = ""
    segments: list[Segment] = []
    paras: list[str] = []
    section = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        m = _SOURCE_RE.match(line)
        if m:
            source = Path(m.group(1))
            continue
        m = _DURATION_RE.match(line)
        if m:
            duration = float(m.group(2))
            continue
        m = _ASR_RE.match(line)
        if m:
            cover = float(m.group(2))
            continue
        m = _AUDIO_RE.match(line)
        if m:
            audio_name = m.group(1)
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "带时间轴文稿":
            m = _TIMELINE_RE.match(line)
            if m:
                segments.append(Segment(parse_ts(m.group(1)), parse_ts(m.group(1)), m.group(2).strip()))
        elif section == "连续文稿" and line.strip():
            paras.append(line.strip())
    if segments and not cover:
        cover = sum(max(0.0, s.end - s.start) for s in segments)
    if not duration and segments:
        duration = max(s.end for s in segments)
    return Transcript(
        source=source,
        title=title,
        duration=duration,
        segments=segments,
        cover=cover,
        audio_name=audio_name,
        reused=True,
    )


# ------------------------------------------------------------------- system

def total_ram_gb() -> float:
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemoryStatus()
            stat.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / 1e9
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:
        return 8.0


def default_workers() -> int:
    return 2 if total_ram_gb() >= 12 else 1


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def log_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "video-to-text" / "app.log"


def append_log(message: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass
