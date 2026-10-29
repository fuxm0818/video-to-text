"""Local-only HTTP server and JSON API for the browser UI."""
from __future__ import annotations

import html
import json
import mimetypes
import secrets
import shutil
import socketserver
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, config, core, dialogs
from .jobs import JobManager

WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_TYPES = {
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "logo.svg": "image/svg+xml",
}
FILE_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "audio": "audio/mp4",
}


class AppContext:
    def __init__(self, output_dir: str | None = None, check_models: bool = True,
                 token: str | None = None) -> None:
        self.token = token or secrets.token_urlsafe(24)
        self.manager = JobManager()
        self.settings = config.load_settings()
        if output_dir:
            self.settings["output_dir"] = str(Path(output_dir).expanduser())
        self.version = __version__
        self.models_ready: bool | None = None
        self.started_at = time.time()
        self._lock = threading.RLock()
        if check_models:
            threading.Thread(target=self._check_models, daemon=True).start()

    def _check_models(self) -> None:
        try:
            ready = core.models_cached()
        except Exception:
            ready = False
        with self._lock:
            self.models_ready = ready

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            merged = dict(self.settings)
            if "output_dir" in patch and isinstance(patch["output_dir"], str):
                candidate = patch["output_dir"].strip()
                if candidate and Path(candidate).expanduser().is_file():
                    raise RuntimeError("输出位置不能是文件，请选择文件夹")
                merged["output_dir"] = candidate
            if "formats" in patch and isinstance(patch["formats"], list):
                merged["formats"] = [f for f in patch["formats"] if f in core.TEXT_FORMATS]
            if "audio_format" in patch and patch["audio_format"] in core.AUDIO_FORMATS:
                merged["audio_format"] = patch["audio_format"]
            if "workers" in patch:
                try:
                    merged["workers"] = max(1, min(4, int(patch["workers"])))
                except (TypeError, ValueError):
                    pass
            if not merged.get("formats") and merged.get("audio_format") == "none":
                raise RuntimeError("请至少选择一种输出内容")
            if not merged.get("output_dir"):
                merged["output_dir"] = str(config.default_output_dir())
            self.settings = config.save_settings(merged)
            return dict(self.settings)

    def snapshot(self) -> dict:
        state = self.manager.snapshot()
        with self._lock:
            if state.get("job", {}).get("model_state") == "ready":
                self.models_ready = True
            state["settings"] = dict(self.settings)
            state["version"] = self.version
            state["models_ready"] = self.models_ready
            state["server_started_at"] = self.started_at
        return state


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoToText"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ plumbing

    @property
    def ctx(self) -> AppContext:
        return self.server.context  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # noqa: N802 - stdlib signature
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]  # type: ignore[attr-defined]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _token_ok(self) -> bool:
        supplied = self.headers.get("X-V2T-Token") or ""
        return bool(supplied) and secrets.compare_digest(supplied, self.ctx.token)

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]  # type: ignore[attr-defined]
        return origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status=status)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 2_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求格式不正确") from exc
        if not isinstance(data, dict):
            raise ValueError("请求格式不正确")
        return data

    # -------------------------------------------------------------- routing

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._error("只允许本机访问", 403)
            return
        parsed = urlsplit(self.path)
        path = parsed.path

        if path == "/" and method == "GET":
            self._serve_index()
            return
        if path == "/favicon.ico" and method == "GET":
            self._serve_static("logo.svg")
            return
        if path.startswith("/static/") and method == "GET":
            self._serve_static(path[len("/static/"):])
            return
        if path == "/api/health" and method == "GET":
            self._send_json({"ok": True, "version": self.ctx.version})
            return
        if path == "/api/file" and method == "GET":
            token = (parse_qs(parsed.query).get("token") or [""])[0]
            if not token or not secrets.compare_digest(token, self.ctx.token):
                self._error("无权访问", 403)
                return
            self._serve_output(parse_qs(parsed.query))
            return

        if not path.startswith("/api/"):
            self._error("not found", 404)
            return
        if not self._token_ok():
            self._error("会话已失效，请刷新页面", 403)
            return
        if method == "POST" and not self._origin_ok():
            self._error("请求来源不可信", 403)
            return

        try:
            if path == "/api/state" and method == "GET":
                self._send_json(self.ctx.snapshot())
            elif path == "/api/pick-files" and method == "POST":
                self._send_json({"paths": [str(p) for p in dialogs.pick_files()]})
            elif path == "/api/pick-folder" and method == "POST":
                folder = dialogs.pick_folder()
                self._send_json({"path": str(folder) if folder else ""})
            elif path == "/api/pick-output" and method == "POST":
                folder = dialogs.pick_folder()
                self._send_json({"path": str(folder) if folder else ""})
            elif path == "/api/add" and method == "POST":
                data = self._read_json()
                paths = data.get("paths") or []
                if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                    raise ValueError("路径格式不正确")
                added, skipped = self.ctx.manager.add_paths(
                    paths, Path(self.ctx.settings["output_dir"])
                )
                self._send_json({"added": added, "skipped": skipped,
                                 "state": self.ctx.snapshot()})
            elif path == "/api/remove" and method == "POST":
                data = self._read_json()
                self.ctx.manager.remove(str(data.get("id") or ""))
                self._send_json(self.ctx.snapshot())
            elif path == "/api/clear" and method == "POST":
                self.ctx.manager.clear()
                self._send_json(self.ctx.snapshot())
            elif path == "/api/settings" and method == "POST":
                data = self._read_json()
                settings = self.ctx.update_settings(data)
                self._send_json({"settings": settings, "state": self.ctx.snapshot()})
            elif path == "/api/start" and method == "POST":
                data = self._read_json()
                force = bool(data.get("force"))
                settings = self.ctx.settings
                self.ctx.manager.start(
                    Path(settings["output_dir"]),
                    list(settings.get("formats") or []),
                    str(settings.get("audio_format") or "none"),
                    int(settings.get("workers") or 1),
                    force,
                )
                self._send_json(self.ctx.snapshot())
            elif path == "/api/cancel" and method == "POST":
                canceled = self.ctx.manager.cancel()
                self._send_json({"canceled": canceled, "state": self.ctx.snapshot()})
            elif path == "/api/open-output" and method == "POST":
                folder = self._output_dir()
                folder.mkdir(parents=True, exist_ok=True)
                core.open_folder(folder)
                self._send_json({"opened": str(folder)})
            elif path == "/api/quit" and method == "POST":
                self._send_json({"ok": True})
                threading.Thread(target=self._shutdown, daemon=True).start()
            else:
                self._error("not found", 404)
        except (ValueError, RuntimeError, core.TranscriptionError, dialogs.DialogError) as exc:
            self._error(str(exc), 400)
        except Exception as exc:
            core.append_log(f"HTTP {path} 出错：{exc}")
            self._error("服务出错：" + str(exc)[:200], 500)

    def _output_dir(self) -> Path:
        snapshot = self.ctx.manager.snapshot()
        raw = snapshot.get("output_dir") or self.ctx.settings.get("output_dir")
        return Path(raw).expanduser().resolve()

    def _shutdown(self) -> None:
        time.sleep(0.2)
        try:
            self.ctx.manager.shutdown()
        finally:
            try:
                self.server.shutdown()  # type: ignore[attr-defined]
                self.server.server_close()  # type: ignore[attr-defined]
            except Exception:
                pass

    # --------------------------------------------------------------- files

    def _serve_index(self) -> None:
        path = WEB_DIR / "index.html"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            self._error("界面文件缺失", 500)
            return
        text = text.replace("__V2T_TOKEN__", self.ctx.token)
        text = text.replace("__V2T_VERSION__", html.escape(self.ctx.version))
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, name: str) -> None:
        if name not in STATIC_TYPES:
            self._error("not found", 404)
            return
        path = WEB_DIR / name
        try:
            body = path.read_bytes()
        except OSError:
            self._error("not found", 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES[name])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _serve_output(self, query: dict) -> None:
        task_id = (query.get("id") or [""])[0]
        kind = (query.get("kind") or [""])[0]
        task = self.ctx.manager.task_by_id(task_id)
        if task is None or kind not in task.outputs:
            self._error("文件还没有生成", 404)
            return
        outdir = self._output_dir()
        path = (outdir / task.outputs[kind]).resolve()
        if outdir not in path.parents or not path.is_file():
            self._error("文件不存在", 404)
            return
        content_type = FILE_TYPES.get(kind) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind == "audio" and path.suffix.lower() == ".wav":
            content_type = "audio/wav"
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{quote(path.name)}",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            with path.open("rb") as fh:
                shutil.copyfileobj(fh, self.wfile, length=256 * 1024)
        except (BrokenPipeError, ConnectionResetError):
            pass


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        # HTTPServer.server_bind() resolves socket.getfqdn() on 127.0.0.1, which
        # blocks ~35 s in the packaged macOS app. The hostname is never used.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def __init__(self, address, context: AppContext):
        self.context = context
        super().__init__(address, Handler)


def create_server(context: AppContext, port: int = 8765):
    return LocalServer(("127.0.0.1", port), context)


def _existing_instance(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    return data.get("ok") is True and "version" in data


def serve(context: AppContext, port: int = 8765, open_browser: bool = True):
    try:
        httpd = create_server(context, port)
    except OSError:
        if _existing_instance(port):
            url = f"http://127.0.0.1:{port}/"
            core.append_log(f"已有实例在运行：{url}")
            if open_browser:
                import webbrowser
                webbrowser.open(url)
            context.manager.shutdown()
            return port
        httpd = create_server(context, 0)
    actual = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual}/"
    core.append_log(f"服务启动：{url}")
    if open_browser:
        def _open():
            time.sleep(0.35)
            import webbrowser
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    if sys.stdout:
        print(f"Video to Text 已启动：{url}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        context.manager.shutdown()
        httpd.server_close()
    return actual
