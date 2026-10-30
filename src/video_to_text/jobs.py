"""Background transcription jobs for the desktop window."""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import tempfile
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import core

STAGE_LABELS = {
    "start": "准备中",
    "extract": "抽取音频",
    "asr": "识别中",
    "punctuate": "整理文稿",
    "audio": "导出音频",
    "write": "写入文稿",
}

MODEL_TOTAL_BYTES = 2_100_000_000  # 名义总量，用于下载进度估算（约 2.1 GB）


def model_cache_dir() -> Path:
    return Path(os.environ.get("MODELSCOPE_CACHE") or Path.home() / ".cache" / "modelscope")


def model_cache_bytes() -> int:
    """ModelScope 缓存目录当前大小；只用于显示下载进度，取不到就返回 0。"""
    base = model_cache_dir()
    total = 0
    try:
        for root, _dirs, files in os.walk(base):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        return total
    return total


@dataclass
class Task:
    id: str
    path: Path
    size: int
    duration: float = 0.0
    stem: str = ""
    status: str = "queued"
    stage: str = ""
    message: str = ""
    error: str = ""
    elapsed: float = 0.0
    started_at: float = 0.0
    outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    reused: bool = False
    cover: float = 0.0
    error_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.path.name,
            "path": str(self.path),
            "size": self.size,
            "duration": self.duration,
            "status": self.status,
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, ""),
            "message": self.message,
            "error": self.error,
            "elapsed": self.elapsed,
            "outputs": self.outputs,
            "warnings": self.warnings,
            "reused": self.reused,
            "cover": self.cover,
            "error_detail": self.error_detail,
        }


def _worker_main(task_q, event_q, cancel_evt, threads: int, formats: list[str],
                 audio_format: str, force: bool, temp_prefix: str) -> None:
    os.environ["V2T_THREADS"] = str(threads)
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["MKL_NUM_THREADS"] = str(threads)
    while True:
        task = task_q.get()
        if task is None:
            return

        def send(kind: str, **payload) -> None:
            event_q.put({"type": kind, "id": task["id"], **payload})

        if cancel_evt.is_set():
            send("canceled")
            continue

        def stage(name: str) -> None:
            send("stage", stage=name)

        def log(message: str) -> None:
            send("log", message=message)

        send("stage", stage="start")
        try:
            result = core.transcribe_file(
                Path(task["path"]),
                set(formats),
                audio_format,
                Path(task["outdir"]),
                task["stem"],
                force=force,
                log=log,
                stage=stage,
                temp_prefix=temp_prefix,
            )
            outdir = Path(task["outdir"])
            outputs: dict[str, str] = {}
            for kind, filename in (
                ("md", f"{task['stem']}.md"),
                ("docx", f"{task['stem']}.docx"),
                ("audio", result.audio_name or ""),
            ):
                if filename and (outdir / filename).exists():
                    outputs[kind] = filename
            send(
                "done",
                elapsed=result.elapsed,
                segments=len(result.segments),
                cover=result.cover,
                duration=result.duration,
                warnings=result.warnings,
                reused=result.reused,
                outputs=outputs,
            )
        except BaseException as exc:
            send(
                "error",
                error=str(exc) or exc.__class__.__name__,
                detail=traceback.format_exc()[-1500:],
            )


def _model_worker(event_q) -> None:
    try:
        core.ensure_models(lambda message: event_q.put(("log", message)))
        event_q.put(("done", ""))
    except BaseException as exc:
        event_q.put(("error", f"{exc}\n{traceback.format_exc()[-800:]}"))


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._logs: deque[dict] = deque(maxlen=800)
        self._job = {
            "state": "idle",
            "running": False,
            "canceling": False,
            "total": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "canceled": 0,
            "started_at": 0.0,
            "finished_at": 0.0,
            "message": "",
            "needs_model": False,
            "model_state": "",
            "model_bytes": 0,
            "model_total_bytes": MODEL_TOTAL_BYTES,
        }
        self._thread: threading.Thread | None = None
        self._procs: list[mp.Process] = []
        self._cancel_requested = threading.Event()
        self._cancel_evt = None
        self._temp_prefix = ""
        self._last_output_dir = ""
        self._last_model_poll = 0.0

    # ------------------------------------------------------------- tasks

    def add_paths(self, inputs: list[str], output_dir: Path) -> tuple[int, int]:
        with self._lock:
            if self._job["running"]:
                raise RuntimeError("正在转写，暂不能修改文件列表")
            files = core.collect_media(inputs, skip_dirs=[output_dir])
            existing = {str(t.path.resolve()) for t in self._tasks.values()}
            added_ids: list[str] = []
            skipped = 0
            for path in files:
                key = str(path.resolve())
                if key in existing:
                    skipped += 1
                    continue
                if len(self._tasks) >= core.MAX_FILES:
                    raise RuntimeError(f"一次最多处理 {core.MAX_FILES} 个文件")
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                task = Task(id=uuid.uuid4().hex[:10], path=path, size=size)
                self._tasks[task.id] = task
                self._order.append(task.id)
                added_ids.append(task.id)
            if added_ids:
                self._log(f"添加了 {len(added_ids)} 个文件")
                threading.Thread(target=self._probe, args=(added_ids,), daemon=True).start()
            return len(added_ids), skipped

    def _probe(self, ids: list[str]) -> None:
        for task_id in ids:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is None or task.status != "queued":
                    continue
                path = task.path
            duration = core.probe_duration(path)
            if duration <= 0:
                continue
            with self._lock:
                task = self._tasks.get(task_id)
                if task is not None:
                    task.duration = duration

    def remove(self, task_id: str) -> None:
        with self._lock:
            if self._job["running"]:
                raise RuntimeError("正在转写，暂不能修改文件列表")
            self._tasks.pop(task_id, None)
            if task_id in self._order:
                self._order.remove(task_id)

    def clear(self) -> None:
        with self._lock:
            if self._job["running"]:
                raise RuntimeError("正在转写，暂不能清空")
            self._tasks.clear()
            self._order.clear()

    def task_by_id(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    # --------------------------------------------------------------- job

    def start(self, output_dir: Path, formats: list[str], audio_format: str,
              workers: int, force: bool, only_ids: list[str] | None = None) -> None:
        formats = sorted(set(formats) & core.TEXT_FORMATS)
        if not formats and audio_format == "none":
            raise RuntimeError("请至少选择一种输出内容")
        if audio_format not in core.AUDIO_FORMATS:
            raise RuntimeError("不支持的音频格式")
        with self._lock:
            if self._job["running"]:
                raise RuntimeError("已有转写任务在运行")
            if not self._order:
                raise RuntimeError("请先选择视频或音频文件")
            candidate_ids = [
                tid for tid in (self._order if only_ids is None else only_ids)
                if tid in self._tasks
            ]
            if not candidate_ids:
                raise RuntimeError("请先选择视频或音频文件")
            output_dir = Path(output_dir).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            self._last_output_dir = str(output_dir)
            stems = core.assign_stems(
                [self._tasks[tid].path for tid in candidate_ids], output_dir
            )
            pending: list[Task] = []
            skipped = 0
            needs_model = False
            for task_id in candidate_ids:
                task = self._tasks[task_id]
                task.stem = stems[str(task.path.resolve())]
                task.status = "queued"
                task.stage = ""
                task.message = ""
                task.error = ""
                task.error_detail = ""
                task.outputs = {}
                task.warnings = []
                task.reused = False
                task.cover = 0.0
                task.elapsed = 0.0
                task.started_at = 0.0
                md = output_dir / f"{task.stem}.md"
                docx = output_dir / f"{task.stem}.docx"
                audio = output_dir / f"{task.stem}.{audio_format}" if audio_format != "none" else None
                md_ok = md.exists() and core.markdown_source(md) == str(task.path.resolve())
                existing: dict[str, str] = {}
                for kind, path in (("md", md), ("docx", docx), ("audio", audio)):
                    if path is not None and path.exists():
                        existing[kind] = path.name
                need = False
                need_asr = False
                if force:
                    need = bool(formats) or bool(audio)
                    need_asr = bool(formats)
                else:
                    if "md" in formats and not md.exists():
                        need = need_asr = True
                    if "docx" in formats and not docx.exists():
                        need = True
                        if not md_ok:
                            need_asr = True
                    if audio is not None and not audio.exists():
                        need = True
                if need:
                    pending.append(task)
                    needs_model = needs_model or need_asr
                else:
                    task.status = "skipped"
                    task.message = "输出已存在，跳过"
                    task.outputs = existing
                    skipped += 1

            self._job = {
                "state": "running" if pending else "done",
                "running": bool(pending),
                "canceling": False,
                "total": len(candidate_ids),
                "completed": skipped,
                "failed": 0,
                "skipped": skipped,
                "canceled": 0,
                "started_at": time.time(),
                "finished_at": 0.0 if pending else time.time(),
                "message": "准备开始" if pending else "所选文件的输出都已存在，无需重跑",
                "needs_model": needs_model,
                "model_state": "pending" if needs_model else "",
                "model_bytes": 0,
                "model_total_bytes": MODEL_TOTAL_BYTES,
            }
            self._cancel_requested.clear()
            self._cancel_evt = None
            self._procs = []
            self._last_output_dir = str(output_dir)
            if not pending:
                self._log("所选文件均已有输出，跳过")
                return
            self._log(f"开始转写 {len(pending)} 个文件（并发 {workers}）")
            self._temp_prefix = f"v2t-{int(time.time())}-{uuid.uuid4().hex[:4]}-"
            self._thread = threading.Thread(
                target=self._run,
                args=(pending, output_dir, formats, audio_format, workers, force),
                daemon=True,
            )
            self._thread.start()

    def cancel(self) -> bool:
        with self._lock:
            if not self._job["running"]:
                return False
            self._job["canceling"] = True
            self._job["message"] = "正在取消…"
        self._cancel_requested.set()
        if self._cancel_evt is not None:
            try:
                self._cancel_evt.set()
            except Exception:
                pass
        self._log("收到取消请求", level="warn")
        self._terminate()
        return True

    def shutdown(self) -> None:
        self._cancel_requested.set()
        if self._cancel_evt is not None:
            try:
                self._cancel_evt.set()
            except Exception:
                pass
        self._terminate()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)

    # ------------------------------------------------------------ internals

    def _log(self, message: str, level: str = "info", task: str = "") -> None:
        entry = {"t": time.time(), "level": level, "message": message, "task": task}
        with self._lock:
            self._logs.append(entry)
        core.append_log(("[%s] " % task if task else "") + message)

    def _poll_model_bytes(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_model_poll < 1.0:
            return
        self._last_model_poll = now
        size = model_cache_bytes()
        with self._lock:
            self._job["model_bytes"] = max(int(self._job.get("model_bytes") or 0), size)

    def _prepare_models(self, ctx) -> bool:
        with self._lock:
            self._job["model_state"] = "checking"
            self._job["message"] = "检查语音模型"
        self._log("检查语音模型")
        event_q = ctx.Queue()
        proc = ctx.Process(target=_model_worker, args=(event_q,), daemon=True)
        proc.start()
        self._procs = [proc]
        while True:
            if self._cancel_requested.is_set():
                self._terminate()
                with self._lock:
                    self._job["model_state"] = "canceled"
                return False
            self._poll_model_bytes()
            try:
                kind, payload = event_q.get(timeout=0.4)
            except queue.Empty:
                if not proc.is_alive():
                    proc.join(timeout=1)
                    with self._lock:
                        self._job["model_state"] = "error"
                        self._job["message"] = "语音模型准备失败（进程异常退出）"
                    self._log("语音模型准备失败：模型进程异常退出", level="error")
                    return False
                continue
            if kind == "log":
                with self._lock:
                    if self._job["model_state"] != "downloading" and "下载模型" in payload:
                        self._job["model_state"] = "downloading"
                    self._job["message"] = payload
                self._poll_model_bytes(force=True)
                self._log(payload)
            elif kind == "done":
                proc.join(timeout=5)
                with self._lock:
                    self._job["model_state"] = "ready"
                    self._job["message"] = "语音模型已就绪"
                self._procs = []
                return True
            elif kind == "error":
                proc.join(timeout=5)
                with self._lock:
                    self._job["model_state"] = "error"
                    self._job["message"] = "语音模型准备失败"
                self._log(f"语音模型准备失败：{payload}", level="error")
                return False

    def _run(self, pending: list[Task], output_dir: Path, formats: list[str],
             audio_format: str, workers: int, force: bool) -> None:
        ctx = mp.get_context("spawn")
        task_q = event_q = None
        procs: list[mp.Process] = []
        try:
            if self._job["needs_model"]:
                if not self._prepare_models(ctx):
                    if self._cancel_requested.is_set():
                        self._mark_canceled(pending)
                    else:
                        self._mark_failed(pending, self._job["message"] or "语音模型准备失败")
                    self._finish(canceled=self._cancel_requested.is_set())
                    return

            if self._cancel_requested.is_set():
                self._mark_canceled(pending)
                self._finish(canceled=True)
                return

            n = max(1, min(int(workers), len(pending)))
            task_q = ctx.Queue()
            event_q = ctx.Queue()
            self._cancel_evt = ctx.Event()
            threads = max(1, (os.cpu_count() or 4) // n)
            for _ in range(n):
                proc = ctx.Process(
                    target=_worker_main,
                    args=(task_q, event_q, self._cancel_evt, threads, formats,
                          audio_format, force, self._temp_prefix),
                    daemon=True,
                )
                proc.start()
                procs.append(proc)
            self._procs = procs
            for task in pending:
                task_q.put({
                    "id": task.id,
                    "path": str(task.path),
                    "outdir": str(output_dir),
                    "stem": task.stem,
                })
            for _ in procs:
                task_q.put(None)

            remaining = {t.id for t in pending}
            while remaining:
                if self._cancel_requested.is_set():
                    self._terminate()
                    break
                try:
                    event = event_q.get(timeout=0.4)
                except queue.Empty:
                    self._tick()
                    if self._cancel_requested.is_set():
                        break
                    if not any(p.is_alive() for p in procs):
                        # Give already-queued result events one last chance.
                        try:
                            event = event_q.get(timeout=0.3)
                        except queue.Empty:
                            self._mark_failed(
                                [self._tasks[tid] for tid in remaining if tid in self._tasks],
                                "转写进程异常退出",
                            )
                            remaining.clear()
                            break
                    continue
                self._handle(event, remaining)

            if self._cancel_requested.is_set():
                self._mark_canceled(pending)
            else:
                for proc in procs:
                    proc.join(timeout=5)
                if remaining:
                    self._mark_failed(
                        [self._tasks[tid] for tid in remaining if tid in self._tasks],
                        "转写进程异常退出",
                    )
            self._finish(canceled=self._cancel_requested.is_set())
        except BaseException as exc:
            self._log(f"任务异常：{exc}\n{traceback.format_exc()[-1000:]}", level="error")
            self._mark_failed([t for t in pending if t.status in {"queued", "running"}], str(exc))
            self._finish(canceled=self._cancel_requested.is_set())
        finally:
            self._terminate(procs)
            for q in (task_q, event_q):
                if q is not None:
                    try:
                        q.cancel_join_thread()
                        q.close()
                    except Exception:
                        pass
            self._cleanup_temp()

    def _handle(self, event: dict, remaining: set[str]) -> None:
        task_id = event.get("id", "")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            kind = event.get("type")
            if kind == "stage":
                if task.status != "running":
                    task.status = "running"
                    task.started_at = time.time()
                task.stage = event.get("stage", "")
                task.message = STAGE_LABELS.get(task.stage, task.stage)
                self._job["message"] = f"{task.path.name}：{task.message}"
            elif kind == "log":
                message = event.get("message", "")
                task.message = message
                self._log(message, task=task.path.name)
            elif kind == "done":
                task.status = "done"
                task.stage = ""
                task.elapsed = float(event.get("elapsed") or 0)
                task.outputs = event.get("outputs") or {}
                task.warnings = list(event.get("warnings") or [])
                task.reused = bool(event.get("reused"))
                task.cover = float(event.get("cover") or 0)
                task.message = "完成（复用已有文稿）" if task.reused else "完成"
                self._job["completed"] += 1
                self._job["message"] = f"{task.path.name}：完成"
                self._log(
                    f"完成：{len(task.outputs)} 个输出，"
                    f"识别 {event.get('segments', 0)} 段，覆盖 {core.fmt_ts(float(event.get('cover') or 0))}",
                    task=task.path.name,
                )
                for warning in task.warnings:
                    self._log("提示：" + warning, level="warn", task=task.path.name)
                remaining.discard(task_id)
            elif kind == "error":
                task.status = "failed"
                task.stage = ""
                task.error = event.get("error", "未知错误")
                task.error_detail = event.get("detail") or ""
                task.message = "失败"
                self._job["completed"] += 1
                self._job["failed"] += 1
                self._job["message"] = f"{task.path.name}：失败"
                self._log("失败：" + task.error, level="error", task=task.path.name)
                detail = event.get("detail")
                if detail:
                    core.append_log(f"[{task.path.name}] {detail}")
                remaining.discard(task_id)
            elif kind == "canceled":
                task.status = "canceled"
                task.stage = ""
                task.message = "已取消"
                self._job["completed"] += 1
                self._job["canceled"] += 1
                remaining.discard(task_id)

    def _tick(self) -> None:
        now = time.time()
        with self._lock:
            for task in self._tasks.values():
                if task.status == "running" and task.started_at:
                    task.elapsed = now - task.started_at

    def _mark_canceled(self, tasks: list[Task]) -> None:
        with self._lock:
            for task in tasks:
                if task.status in {"queued", "running"}:
                    task.status = "canceled"
                    task.stage = ""
                    task.message = "已取消"
                    task.elapsed = 0.0
                    self._job["completed"] += 1
                    self._job["canceled"] += 1
            self._job["message"] = "已取消"

    def _mark_failed(self, tasks: list[Task], error: str) -> None:
        with self._lock:
            for task in tasks:
                if task.status in {"queued", "running"}:
                    task.status = "failed"
                    task.stage = ""
                    task.error = error
                    task.message = "失败"
                    self._job["completed"] += 1
                    self._job["failed"] += 1

    def _finish(self, canceled: bool = False) -> None:
        with self._lock:
            self._procs = []
            self._job["running"] = False
            self._job["canceling"] = False
            self._job["finished_at"] = time.time()
            if canceled:
                self._job["state"] = "canceled"
                self._job["message"] = "已取消"
            else:
                self._job["state"] = "done"
                failed = self._job["failed"]
                skipped = self._job["skipped"]
                done = self._job["completed"] - failed - skipped - self._job["canceled"]
                self._job["message"] = (
                    f"全部结束：成功 {done}，跳过 {skipped}，失败 {failed}"
                    if failed else f"全部结束：成功 {done}，跳过 {skipped}"
                )
            if self._job["model_state"] == "checking":
                self._job["model_state"] = "canceled" if canceled else "ready"
        self._log(self._job["message"], level="warn" if self._job["failed"] else "info")

    def _terminate(self, procs: list[mp.Process] | None = None) -> None:
        if self._cancel_evt is not None:
            try:
                self._cancel_evt.set()
            except Exception:
                pass
        for proc in procs if procs is not None else self._procs:
            try:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=5)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=2)
            except Exception:
                pass

    def _cleanup_temp(self) -> None:
        if not self._temp_prefix:
            return
        try:
            base = Path(tempfile.gettempdir())
            for path in base.glob(self._temp_prefix + "*"):
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass

    # ----------------------------------------------------------- snapshot

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            tasks = [self._tasks[tid].to_dict() for tid in self._order if tid in self._tasks]
            job = dict(self._job)
            if job["running"] and job["started_at"]:
                job["elapsed"] = now - job["started_at"]
            else:
                job["elapsed"] = (
                    job["finished_at"] - job["started_at"] if job["started_at"] else 0.0
                )
            logs = list(self._logs)[-200:]
        return {
            "job": job,
            "tasks": tasks,
            "logs": logs,
            "output_dir": self._last_output_dir,
        }
