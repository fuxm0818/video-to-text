"""Command line entry point, local server bootstrap and self-test."""
from __future__ import annotations

import argparse
import multiprocessing
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import APP_NAME, __version__, config, core
from .docx import write_docx
from .server import AppContext, create_server, serve


def _say(message: str) -> None:
    if sys.stdout:
        print(message, flush=True)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(
        prog="video-to-text",
        description="把视频/音频转成 Markdown、Word 和音频文件（全部在本机完成）",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--self-test", action="store_true", help="检查安装是否完整后退出")
    parser.add_argument("--no-browser", action="store_true", help="启动界面时不自动打开浏览器")
    parser.add_argument("--port", type=int, default=8765, help="本地界面端口，默认 8765")
    parser.add_argument("--output", help="界面默认输出文件夹")

    sub = parser.add_subparsers(dest="command")
    transcribe = sub.add_parser("transcribe", help="命令行批量转写（无界面）")
    transcribe.add_argument("inputs", nargs="+", help="视频/音频文件或文件夹")
    transcribe.add_argument("-o", "--outdir", default="output", help="输出文件夹")
    transcribe.add_argument("--formats", default="md,docx", help="文稿格式：md,docx；留空表示只要音频")
    transcribe.add_argument("--audio", choices=["m4a", "wav", "none"], default="m4a",
                            help="同时导出的音频格式，默认 m4a")
    transcribe.add_argument("--force", action="store_true", help="已有输出也重新转写")

    args = parser.parse_args(argv)

    if args.self_test:
        ok = self_test()
        return 0 if ok else 1

    if args.command == "transcribe":
        return cli_transcribe(args)

    ctx = AppContext(output_dir=args.output)
    try:
        folder = Path(ctx.settings["output_dir"]).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    core.append_log(f"应用启动，版本 {__version__}")
    serve(ctx, port=args.port, open_browser=not args.no_browser)
    return 0


def _parse_formats(text: str) -> list[str]:
    formats = [f.strip().lower() for f in (text or "").split(",") if f.strip()]
    unknown = [f for f in formats if f not in core.TEXT_FORMATS]
    if unknown:
        raise SystemExit(f"不支持的文稿格式：{', '.join(unknown)}（只支持 md、docx）")
    return formats


def cli_transcribe(args) -> int:
    formats = _parse_formats(args.formats)
    if not formats and args.audio == "none":
        raise SystemExit("--formats 和 --audio 不能同时为空")
    outdir = Path(args.outdir).expanduser().resolve()
    try:
        files = core.collect_media([Path(p) for p in args.inputs])
    except core.TranscriptionError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if not files:
        print("没有可处理的文件", file=sys.stderr)
        return 2
    outdir.mkdir(parents=True, exist_ok=True)
    stems = core.assign_stems(files, outdir)

    need_asr = False
    for path in files:
        stem = stems[str(path.resolve())]
        md = outdir / f"{stem}.md"
        if formats and not (md.exists() and core.markdown_source(md) == str(path.resolve())):
            need_asr = True
            break
    if need_asr:
        try:
            core.ensure_models(lambda message: print(message, flush=True))
        except Exception as exc:
            print(f"语音模型准备失败：{exc}", file=sys.stderr)
            return 2

    failed = 0
    for index, path in enumerate(files, 1):
        stem = stems[str(path.resolve())]
        _say(f"[{index}/{len(files)}] {path.name}")
        stage_names = {
            "extract": "抽取音频", "asr": "语音识别", "punctuate": "整理文稿",
            "audio": "导出音频", "write": "写入文稿",
        }

        def stage(name: str) -> None:
            if name in stage_names:
                _say("    · " + stage_names[name])

        try:
            result = core.transcribe_file(
                path, set(formats), args.audio, outdir, stem,
                force=args.force, stage=stage,
            )
            made = []
            if "md" in formats:
                made.append(f"{stem}.md")
            if "docx" in formats:
                made.append(f"{stem}.docx")
            if result.audio_name:
                made.append(result.audio_name)
            _say(f"    完成：{'、'.join(made) if made else '无输出'}"
                 f"（识别 {len(result.segments)} 段，覆盖 {result.ratio * 100:.0f}%）")
            for warning in result.warnings:
                print(f"    提示：{warning}", file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f"    失败：{exc}", file=sys.stderr)
    _say(f"全部结束：成功 {len(files) - failed}，失败 {failed}；输出在 {outdir}")
    return 1 if failed else 0


# ------------------------------------------------------------------ self-test

def self_test() -> bool:
    lines: list[str] = []
    ok = True

    def note(message: str) -> None:
        lines.append(message)
        _say(message)

    def fail(message: str) -> None:
        nonlocal ok
        ok = False
        note("FAIL " + message)

    note(f"{APP_NAME} {__version__} self-test")
    note(f"Python {sys.version.split()[0]} / {sys.platform}")
    note(f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")

    ffmpeg = core.tool_path("ffmpeg")
    ffprobe = core.tool_path("ffprobe")
    note(f"ffmpeg={ffmpeg}")
    note(f"ffprobe={ffprobe or '未安装（改用 ffmpeg 读取媒体信息）'}")
    if not ffmpeg:
        fail("ffmpeg 缺失")
    else:
        try:
            r = core.run([ffmpeg, "-version"])
            if r.returncode != 0:
                fail("ffmpeg 无法运行：" + (r.stderr or "")[:200])
            else:
                note("ffmpeg " + r.stdout.splitlines()[0][:120])
        except Exception as exc:
            fail(f"ffmpeg 运行失败：{exc}")

    for module in ("torch", "funasr", "modelscope"):
        try:
            mod = __import__(module)
            note(f"{module} {getattr(mod, '__version__', '?')}")
        except Exception as exc:
            fail(f"导入 {module} 失败：{exc}")

    with tempfile.TemporaryDirectory(prefix="v2t-selftest-") as tmp:
        tmpdir = Path(tmp)
        try:
            source = tmpdir / "tone.wav"
            r = core.run([
                ffmpeg, "-y", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(source),
            ])
            if r.returncode != 0 or not source.exists():
                fail("生成测试音频失败：" + (r.stderr or "")[:200])
            else:
                note(f"测试音频 {source.stat().st_size} B，时长 {core.probe_duration(source):.2f}s")
                extracted = tmpdir / "extracted.wav"
                core.extract_audio(source, extracted)
                if extracted.stat().st_size <= 44:
                    fail("音轨抽取结果为空")
                else:
                    note("音轨抽取 OK")
                m4a = tmpdir / "tone.m4a"
                core.export_audio(source, m4a, "m4a")
                if not m4a.exists() or m4a.stat().st_size == 0:
                    fail("M4A 导出结果为空")
                else:
                    note(f"M4A 导出 OK（{m4a.stat().st_size} B）")
        except Exception as exc:
            fail(f"音视频检查失败：{exc}")

        try:
            class FakePunc:
                punc_model = object()
                punc_kwargs = {}

                def inference(self, text, model=None, kwargs=None):
                    return [{"text": text.replace("你好世界", "你好，世界。")}]

            chunks = [core.Segment(0.0, 1.0, "你好世界")]
            sents = core.sentences_from(chunks, FakePunc())
            if not sents or sents[0].text != "你好，世界。":
                fail(f"断句/标点检查失败：{[s.text for s in sents]}")
            else:
                note("断句/标点 OK")
        except Exception as exc:
            fail(f"断句/标点检查异常：{exc}")

        try:
            t = core.Transcript(
                source=Path("/tmp/example.mp4"),
                title="自检文稿",
                duration=120.0,
                segments=[core.Segment(0.0, 3.0, "这是一段测试文字。"),
                          core.Segment(3.0, 6.0, "第二句话也在这里。")],
                cover=6.0,
            )
            md = core.render_markdown(t)
            if "未经人工校对" not in md or "## 带时间轴文稿" not in md:
                fail("Markdown 内容检查失败")
            else:
                note(f"Markdown OK（{len(md)} 字符）")
            docx_path = tmpdir / "sample.docx"
            write_docx(docx_path, core.docx_blocks(t), title=t.title)
            with zipfile.ZipFile(docx_path) as zf:
                names = set(zf.namelist())
                required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml"}
                if not required.issubset(names):
                    fail("DOCX 结构不完整")
                else:
                    ET.fromstring(zf.read("word/document.xml"))
                    note(f"DOCX OK（{docx_path.stat().st_size} B）")
        except Exception as exc:
            fail(f"文稿导出检查失败：{exc}")

        try:
            ctx = AppContext(output_dir=str(tmpdir), check_models=False,
                             token="self-test-token")
            httpd = create_server(ctx, 0)
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{port}"
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=5) as resp:
                    health = resp.read().decode()
                if '"ok": true' not in health:
                    fail("本地服务健康检查失败")
                else:
                    note("本地服务 OK")
                try:
                    urllib.request.urlopen(url + "/api/state", timeout=5)
                    fail("本地服务未拦截无令牌请求")
                except urllib.error.HTTPError as exc:
                    if exc.code == 403:
                        note("本地服务权限检查 OK")
                    else:
                        fail(f"本地服务权限检查返回 {exc.code}")
                req = urllib.request.Request(
                    url + "/api/state", headers={"X-V2T-Token": "self-test-token"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    state = resp.read().decode()
                if '"settings"' not in state:
                    fail("本地服务状态接口异常")
                with urllib.request.urlopen(url + "/", timeout=5) as resp:
                    page = resp.read().decode()
                if "self-test-token" not in page or "视频转文字" not in page:
                    fail("界面页面检查失败")
                else:
                    note("界面页面 OK")
            finally:
                httpd.shutdown()
                httpd.server_close()
                ctx.manager.shutdown()
        except Exception as exc:
            fail(f"本地服务检查失败：{exc}")

    note("SELF-TEST " + ("OK" if ok else "FAILED"))
    log = core.log_path().with_name("self-test.log")
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        note(f"自检日志：{log}")
    except OSError:
        pass
    return ok
