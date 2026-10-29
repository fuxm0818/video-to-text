(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var els = {
    fileCount: $("file-count"),
    clearFiles: $("clear-files"),
    pickFiles: $("pick-files"),
    pickFolder: $("pick-folder"),
    manualPaths: $("manual-paths"),
    addManual: $("add-manual"),
    empty: $("empty"),
    fileList: $("file-list"),
    outputDir: $("output-dir"),
    pickOutput: $("pick-output"),
    fmtMd: $("fmt-md"),
    fmtDocx: $("fmt-docx"),
    audioFormat: $("audio-format"),
    workers: $("workers"),
    force: $("force"),
    modelNote: $("model-note"),
    start: $("start"),
    startHint: $("start-hint"),
    jobState: $("job-state"),
    progressTitle: $("progress-title"),
    progressDetail: $("progress-detail"),
    cancel: $("cancel"),
    openOutput: $("open-output"),
    bar: $("bar"),
    barFill: $("bar-fill"),
    statDone: $("stat-done"),
    statFailed: $("stat-failed"),
    statSkipped: $("stat-skipped"),
    statCanceled: $("stat-canceled"),
    statElapsed: $("stat-elapsed"),
    jobList: $("job-list"),
    log: $("log"),
    logCount: $("log-count"),
    quit: $("quit"),
    toast: $("toast")
  };

  var meta = document.querySelector('meta[name="v2t-token"]');
  var TOKEN = meta ? (meta.getAttribute("content") || "").trim() : "";

  var app = {
    tasks: [],
    job: {},
    settings: null,
    settingsLoaded: false,
    settingsDirty: false,
    settingsTimer: 0,
    outputDir: "",
    lastRunDir: "",
    modelsReady: null,
    running: false,
    picking: false,
    dead: false,
    polling: false,
    failures: 0,
    timer: 0,
    toastTimer: 0,
    fileKey: "",
    jobOrderKey: "",
    jobNodes: new Map(),
    logText: "",
    lastTitle: ""
  };

  // ------------------------------------------------------------- helpers

  function setText(el, value) {
    if (el && el.textContent !== value) el.textContent = value;
  }

  function show(el, visible) {
    if (el) el.classList.toggle("hidden", !visible);
  }

  function setChecked(el, value) {
    if (el && el.checked !== value) el.checked = value;
  }

  function pad2(n) { return n < 10 ? "0" + n : String(n); }

  function fmtClock(seconds) {
    var total = Math.max(0, Math.round(Number(seconds) || 0));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    return h ? h + ":" + pad2(m) + ":" + pad2(s) : pad2(m) + ":" + pad2(s);
  }

  function fmtSize(bytes) {
    var n = Number(bytes) || 0;
    if (n < 1024) return n + " B";
    var units = ["KB", "MB", "GB", "TB"];
    var value = n / 1024;
    var i = 0;
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024;
      i += 1;
    }
    return (value >= 100 ? value.toFixed(0) : value.toFixed(1)) + " " + units[i];
  }

  function fmtLogTime(ts) {
    var d = new Date((Number(ts) || 0) * 1000);
    return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
  }

  function showToast(message, kind) {
    if (!message) return;
    els.toast.textContent = message;
    els.toast.classList.toggle("error", kind === "error");
    els.toast.classList.add("show");
    clearTimeout(app.toastTimer);
    app.toastTimer = setTimeout(function () {
      els.toast.classList.remove("show");
    }, kind === "error" ? 5600 : 3200);
  }

  // ----------------------------------------------------------------- api

  async function api(path, options) {
    var opts = options || {};
    var init = {
      method: opts.method || "GET",
      cache: "no-store",
      headers: { "X-V2T-Token": TOKEN }
    };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    var res;
    try {
      res = await fetch(path, init);
    } catch (err) {
      var netErr = new Error("无法连接本地服务");
      netErr.network = true;
      throw netErr;
    }
    var data = null;
    try {
      data = await res.json();
    } catch (err) {
      data = null;
    }
    if (!res.ok) {
      var httpErr = new Error((data && data.error) || ("请求失败（HTTP " + res.status + "）"));
      httpErr.status = res.status;
      throw httpErr;
    }
    return data || {};
  }

  // ------------------------------------------------------------ settings

  function settingsValid() {
    var formats = (els.fmtMd.checked ? 1 : 0) + (els.fmtDocx.checked ? 1 : 0);
    return formats > 0 || els.audioFormat.value !== "none";
  }

  function readSettings() {
    var formats = [];
    if (els.fmtMd.checked) formats.push("md");
    if (els.fmtDocx.checked) formats.push("docx");
    return {
      formats: formats,
      audio_format: els.audioFormat.value,
      workers: Number(els.workers.value) || 1,
      output_dir: els.outputDir.value
    };
  }

  function applySettings(settings) {
    if (!settings) return;
    var formats = Array.isArray(settings.formats) ? settings.formats : [];
    setChecked(els.fmtMd, formats.indexOf("md") >= 0);
    setChecked(els.fmtDocx, formats.indexOf("docx") >= 0);
    if (settings.audio_format && els.audioFormat.value !== settings.audio_format) {
      els.audioFormat.value = settings.audio_format;
    }
    if (settings.workers) els.workers.value = String(settings.workers);
    if (typeof settings.output_dir === "string" && els.outputDir.value !== settings.output_dir) {
      els.outputDir.value = settings.output_dir;
      els.outputDir.title = settings.output_dir;
    }
    app.settings = settings;
    app.settingsLoaded = true;
    if (settings.output_dir) app.outputDir = settings.output_dir;
  }

  async function pushSettings() {
    clearTimeout(app.settingsTimer);
    if (!settingsValid()) return false;
    var payload = readSettings();
    app.settingsDirty = true;
    try {
      var res = await api("/api/settings", { method: "POST", body: payload });
      app.settingsDirty = false;
      if (res.settings) applySettings(res.settings);
      return true;
    } catch (err) {
      app.settingsDirty = false;
      showToast(err.message || "保存设置失败", "error");
      return false;
    }
  }

  function scheduleSettings() {
    app.settingsDirty = true;
    updateControls();
    clearTimeout(app.settingsTimer);
    if (!settingsValid()) return;
    app.settingsTimer = setTimeout(function () { pushSettings(); }, 260);
  }

  // -------------------------------------------------------------- render

  function fileItem(task) {
    var li = document.createElement("li");
    li.className = "file-item";

    var ext = document.createElement("span");
    ext.className = "file-ext";
    var dot = task.name.lastIndexOf(".");
    ext.textContent = dot > 0 ? task.name.slice(dot + 1).slice(0, 5).toUpperCase() : "MEDIA";

    var main = document.createElement("div");
    main.className = "file-main";
    var name = document.createElement("span");
    name.className = "file-name";
    name.textContent = task.name;
    name.title = task.path;
    var meta = document.createElement("span");
    meta.className = "file-meta";
    meta.textContent = task.size ? fmtSize(task.size) : task.path;
    meta.title = task.path;
    main.appendChild(name);
    main.appendChild(meta);

    var duration = document.createElement("span");
    duration.className = "file-duration";
    duration.textContent = task.duration ? fmtClock(task.duration) : "";

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "file-remove";
    remove.textContent = "移除";
    remove.setAttribute("aria-label", "移除 " + task.name);
    remove.addEventListener("click", function () {
      removeTask(task.id);
    });

    li.appendChild(ext);
    li.appendChild(main);
    li.appendChild(duration);
    li.appendChild(remove);
    return li;
  }

  function renderFiles() {
    var tasks = app.tasks;
    var key = tasks.map(function (t) { return t.id + ":" + Math.round(t.duration || 0); }).join(",");
    if (key !== app.fileKey) {
      app.fileKey = key;
      var frag = document.createDocumentFragment();
      tasks.forEach(function (task) { frag.appendChild(fileItem(task)); });
      els.fileList.replaceChildren(frag);
    }
    var locked = app.running || app.picking || app.dead;
    els.fileList.querySelectorAll(".file-remove").forEach(function (btn) {
      btn.disabled = locked;
    });
    show(els.empty, tasks.length === 0);
    show(els.clearFiles, tasks.length > 0 && !locked);

    var bytes = tasks.reduce(function (sum, t) { return sum + (t.size || 0); }, 0);
    var label = tasks.length + " 个文件" + (bytes ? " · " + fmtSize(bytes) : "");
    setText(els.fileCount, label);
  }

  function statusLabel(task) {
    switch (task.status) {
      case "running": return task.stage_label || "处理中";
      case "done": return "完成";
      case "failed": return "失败";
      case "skipped": return "跳过";
      case "canceled": return "已取消";
      default: return "等待";
    }
  }

  function outputLabel(kind, filename) {
    if (kind === "md") return "MD";
    if (kind === "docx") return "DOCX";
    var dot = filename.lastIndexOf(".");
    return dot > 0 ? filename.slice(dot + 1).toUpperCase() : "音频";
  }

  function makeJobNode() {
    var li = document.createElement("li");
    li.className = "job-item";

    var status = document.createElement("span");
    status.className = "job-status";

    var main = document.createElement("div");
    main.className = "job-main";
    var name = document.createElement("span");
    name.className = "job-name";
    var detail = document.createElement("div");
    detail.className = "job-detail";
    var error = document.createElement("p");
    error.className = "job-error hidden";
    var warning = document.createElement("p");
    warning.className = "job-warning hidden";
    main.appendChild(name);
    main.appendChild(detail);
    main.appendChild(error);
    main.appendChild(warning);

    var outputs = document.createElement("div");
    outputs.className = "job-outputs";

    li.appendChild(status);
    li.appendChild(main);
    li.appendChild(outputs);
    return { li: li, status: status, name: name, detail: detail, error: error, warning: warning, outputs: outputs, sig: "" };
  }

  function taskSignature(task) {
    return [
      task.status, task.stage, task.stage_label, task.elapsed, task.reused,
      task.error, (task.warnings || []).join("\u0001"), task.duration, task.size,
      JSON.stringify(task.outputs || {})
    ].join("\u0002");
  }

  function renderJobNode(node, task) {
    var sig = taskSignature(task);
    if (sig === node.sig) return;
    node.sig = sig;

    node.status.className = "job-status status-" + task.status;
    setText(node.status, statusLabel(task));
    setText(node.name, task.name);
    node.name.title = task.path;

    var parts = [];
    if (task.duration) parts.push("时长 " + fmtClock(task.duration));
    if (task.size) parts.push(fmtSize(task.size));
    if (task.status === "running") {
      if (task.stage_label) parts.push(task.stage_label);
      if (task.elapsed) parts.push(fmtClock(task.elapsed));
    } else if (task.status === "done") {
      if (task.elapsed) parts.push("用时 " + fmtClock(task.elapsed));
      if (task.reused) parts.push("复用已有文稿");
    } else if (task.status === "queued") {
      parts.push("等待开始");
    } else if (task.status === "skipped") {
      parts.push("输出已存在");
    }
    var detailText = parts.join(" · ");
    if (node.detail.textContent !== detailText) node.detail.textContent = detailText;

    var failed = task.status === "failed" && task.error;
    setText(node.error, failed ? String(task.error) : "");
    show(node.error, Boolean(failed));

    var warnings = task.warnings || [];
    var warningText = warnings.length ? "提示：" + warnings.join("；") : "";
    setText(node.warning, warningText);
    show(node.warning, Boolean(warningText));

    var outputs = task.outputs || {};
    var kinds = ["md", "docx", "audio"].filter(function (kind) { return outputs[kind]; });
    var outputSig = kinds.map(function (kind) { return kind + "=" + outputs[kind]; }).join("|");
    if (node.outputs.getAttribute("data-sig") !== outputSig) {
      node.outputs.setAttribute("data-sig", outputSig);
      var frag = document.createDocumentFragment();
      kinds.forEach(function (kind) {
        var filename = outputs[kind];
        var a = document.createElement("a");
        a.className = "output-link";
        a.href = "/api/file?" + new URLSearchParams({
          token: TOKEN,
          id: task.id,
          kind: kind
        }).toString();
        a.textContent = outputLabel(kind, filename);
        a.title = "下载 " + filename;
        frag.appendChild(a);
      });
      node.outputs.replaceChildren(frag);
    }
  }

  function renderJobs() {
    var tasks = app.tasks;
    var ids = tasks.map(function (t) { return t.id; });
    var orderKey = ids.join(",");
    var seen = new Set(ids);
    app.jobNodes.forEach(function (node, id) {
      if (!seen.has(id)) {
        node.li.remove();
        app.jobNodes.delete(id);
      }
    });
    if (orderKey !== app.jobOrderKey) {
      app.jobOrderKey = orderKey;
      tasks.forEach(function (task) {
        var node = app.jobNodes.get(task.id);
        if (node) els.jobList.appendChild(node.li);
      });
    }
    tasks.forEach(function (task) {
      var node = app.jobNodes.get(task.id);
      if (!node) {
        node = makeJobNode();
        app.jobNodes.set(task.id, node);
        els.jobList.appendChild(node.li);
      }
      renderJobNode(node, task);
    });
  }

  function renderProgress() {
    var tasks = app.tasks;
    var job = app.job || {};
    var counts = { done: 0, failed: 0, skipped: 0, canceled: 0 };
    tasks.forEach(function (task) {
      if (Object.prototype.hasOwnProperty.call(counts, task.status)) counts[task.status] += 1;
    });
    var finished = counts.done + counts.failed + counts.skipped;
    var total = tasks.length;
    var percent = total ? Math.round((finished / total) * 100) : 0;

    setText(els.statDone, String(counts.done));
    setText(els.statFailed, String(counts.failed));
    setText(els.statSkipped, String(counts.skipped));
    setText(els.statCanceled, String(counts.canceled));
    setText(els.statElapsed, fmtClock(job.elapsed || 0));

    els.barFill.style.width = percent + "%";
    els.bar.setAttribute("aria-valuenow", String(percent));
    els.bar.classList.toggle("is-canceled", !app.running && job.state === "canceled");

    var stateText = "待开始";
    var stateClass = "job-state";
    if (app.dead) {
      stateText = "已退出";
    } else if (app.running) {
      stateText = job.canceling ? "取消中" : "运行中";
      stateClass += " state-running";
    } else if (job.state === "canceled") {
      stateText = "已取消";
      stateClass += " state-canceled";
    } else if (job.state === "done") {
      stateText = "已完成";
      stateClass += " state-done";
    }
    setText(els.jobState, stateText);
    if (els.jobState.className !== stateClass) els.jobState.className = stateClass;

    var title = "等待开始";
    var detail = "选好素材和输出格式后，点击「开始转写」。";
    if (app.dead) {
      title = "程序已退出";
      detail = "可以关闭这个页面了。";
    } else if (app.running) {
      if (job.model_state === "downloading") title = "正在下载语音模型";
      else if (job.model_state === "checking") title = "正在检查语音模型";
      else title = job.canceling ? "正在取消…" : "正在转写";
      detail = job.message || "准备中…";
    } else if (job.state === "canceled") {
      title = "转写已停止";
      detail = "已停止剩余任务，已完成的输出会保留。";
    } else if (job.state === "done") {
      if (!counts.done && !counts.failed && counts.skipped) title = "无需转写";
      else if (counts.done) title = "转写完成";
      else if (counts.failed) title = "转写未完成";
      detail = job.message || "全部任务已结束。";
    } else if (total) {
      title = "准备就绪";
      detail = "共 " + total + " 个文件，点击「开始转写」。";
    }
    setText(els.progressTitle, title);
    setText(els.progressDetail, detail);

    var docTitle = (app.running ? "转写中 " + percent + "% · " : "") + "视频转文字";
    if (app.lastTitle !== docTitle) {
      app.lastTitle = docTitle;
      document.title = docTitle;
    }
  }

  function renderLogs() {
    var logs = app.snapshotLogs || [];
    var lines = logs.map(function (entry) {
      var mark = entry.level === "error" ? "×" : entry.level === "warn" ? "!" : "·";
      var who = entry.task ? "[" + entry.task + "] " : "";
      return fmtLogTime(entry.t) + " " + mark + " " + who + entry.message;
    });
    var text = lines.join("\n");
    if (text !== app.logText) {
      app.logText = text;
      var nearBottom = els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < 48;
      els.log.textContent = text;
      if (nearBottom) els.log.scrollTop = els.log.scrollHeight;
    }
    setText(els.logCount, logs.length ? "· " + logs.length + " 条" : "");
  }

  function updateControls() {
    var locked = app.running || app.picking || app.dead;
    [
      els.pickFiles, els.pickFolder, els.addManual, els.manualPaths,
      els.pickOutput, els.fmtMd, els.fmtDocx, els.audioFormat, els.workers, els.force
    ].forEach(function (el) {
      if (el) el.disabled = locked;
    });
    show(els.clearFiles, app.tasks.length > 0 && !locked);
    show(els.cancel, app.running);
    if (els.cancel) els.cancel.disabled = !app.running || Boolean(app.job && app.job.canceling);
    show(els.openOutput, Boolean(app.outputDir) && !app.dead);
    if (els.quit) els.quit.disabled = app.dead;
    if (els.start) els.start.disabled = !canStart();

    var hint = "";
    if (app.dead) hint = "程序已退出";
    else if (app.running) hint = "正在转写中，请稍候";
    else if (app.picking) hint = "等待选择…";
    else if (!settingsValid()) hint = "请至少选择 Markdown、Word 或音频中的一种";
    else if (!app.tasks.length) hint = "先选择至少一个文件";
    else hint = "将处理 " + app.tasks.length + " 个文件";
    setText(els.startHint, hint);

    if (els.pickFiles) els.pickFiles.classList.toggle("is-busy", app.picking);
    if (els.pickFolder) els.pickFolder.classList.toggle("is-busy", app.picking);

    var wantsText = els.fmtMd.checked || els.fmtDocx.checked;
    show(els.modelNote, wantsText && app.modelsReady === false && !app.running);
  }

  function canStart() {
    return !app.dead && !app.running && !app.picking && app.tasks.length > 0 && settingsValid();
  }

  function applySnapshot(snap) {
    if (!snap || typeof snap !== "object") return;
    app.job = snap.job || {};
    app.tasks = Array.isArray(snap.tasks) ? snap.tasks : [];
    app.running = Boolean(app.job.running);
    if (snap.models_ready !== undefined) app.modelsReady = snap.models_ready;
    if (snap.output_dir) app.lastRunDir = snap.output_dir;
    if (snap.settings && !app.settingsDirty) applySettings(snap.settings);
    if (Array.isArray(snap.logs)) app.snapshotLogs = snap.logs;

    renderFiles();
    renderJobs();
    renderProgress();
    renderLogs();
    updateControls();
  }

  // ------------------------------------------------------------- actions

  async function addPaths(paths) {
    if (!paths || !paths.length) return;
    var res = await api("/api/add", { method: "POST", body: { paths: paths } });
    if (res.state) applySnapshot(res.state);
    var added = res.added || 0;
    var skipped = res.skipped || 0;
    if (added && skipped) showToast("已添加 " + added + " 个文件，" + skipped + " 个已在列表中");
    else if (added) showToast("已添加 " + added + " 个文件");
    else if (skipped) showToast("这些文件已经在列表里了");
    else showToast("没有找到可处理的音视频文件", "error");
  }

  async function pick(kind) {
    if (app.picking || app.running || app.dead) return;
    app.picking = true;
    updateControls();
    try {
      var res = kind === "files"
        ? await api("/api/pick-files", { method: "POST" })
        : await api("/api/pick-folder", { method: "POST" });
      if (kind === "files") {
        if (res.paths && res.paths.length) await addPaths(res.paths);
      } else if (res.path) {
        await addPaths([res.path]);
      }
    } catch (err) {
      showToast(err.message || "选择文件失败", "error");
    } finally {
      app.picking = false;
      updateControls();
      refresh();
    }
  }

  async function addManualPaths() {
    var raw = els.manualPaths.value || "";
    var paths = raw.split(/[\r\n]+/).map(function (line) { return line.trim(); }).filter(Boolean);
    if (!paths.length) {
      showToast("请先粘贴文件或文件夹路径", "error");
      return;
    }
    els.addManual.classList.add("is-busy");
    try {
      await addPaths(paths);
      els.manualPaths.value = "";
    } catch (err) {
      showToast(err.message || "添加失败", "error");
    } finally {
      els.addManual.classList.remove("is-busy");
      refresh();
    }
  }

  async function removeTask(id) {
    if (app.running) return;
    try {
      var res = await api("/api/remove", { method: "POST", body: { id: id } });
      applySnapshot(res);
    } catch (err) {
      showToast(err.message || "移除失败", "error");
    }
  }

  async function clearFiles() {
    if (app.running) return;
    try {
      var res = await api("/api/clear", { method: "POST" });
      applySnapshot(res);
    } catch (err) {
      showToast(err.message || "清空失败", "error");
    }
  }

  async function pickOutputDir() {
    if (app.picking || app.running || app.dead) return;
    app.picking = true;
    updateControls();
    try {
      var res = await api("/api/pick-output", { method: "POST" });
      if (res.path) {
        els.outputDir.value = res.path;
        els.outputDir.title = res.path;
        app.settingsDirty = true;
        await pushSettings();
      }
    } catch (err) {
      showToast(err.message || "选择文件夹失败", "error");
    } finally {
      app.picking = false;
      updateControls();
    }
  }

  async function startJob() {
    if (!canStart()) {
      if (!app.tasks.length) showToast("请先选择视频或音频文件", "error");
      else if (!settingsValid()) showToast("请至少选择一种输出内容", "error");
      return;
    }
    els.start.classList.add("is-busy");
    try {
      var saved = await pushSettings();
      if (!saved) return;
      var res = await api("/api/start", { method: "POST", body: { force: els.force.checked } });
      applySnapshot(res);
      if (res.job && res.job.needs_model && res.models_ready === false) {
        showToast("首次运行需要下载语音模型（约 2.1 GB），请保持网络连接");
      }
    } catch (err) {
      showToast(err.message || "启动失败", "error");
    } finally {
      els.start.classList.remove("is-busy");
      refresh();
    }
  }

  async function cancelJob() {
    try {
      var res = await api("/api/cancel", { method: "POST" });
      if (res.state) applySnapshot(res.state);
      if (res.canceled) showToast("已请求取消，正在停止任务…");
      else showToast("当前没有正在运行的任务");
    } catch (err) {
      showToast(err.message || "取消失败", "error");
    }
  }

  async function openOutput() {
    try {
      await api("/api/open-output", { method: "POST" });
    } catch (err) {
      showToast(err.message || "无法打开文件夹", "error");
    }
  }

  async function quitApp() {
    if (app.dead) return;
    if (app.running && !window.confirm("正在转写，退出会中断任务。确定退出吗？")) return;
    try {
      await api("/api/quit", { method: "POST" });
    } catch (err) {
      // The server may close before the response is read.
    }
    markDead("程序已退出，可以关闭这个页面。");
  }

  function markDead(message) {
    if (app.dead) return;
    app.dead = true;
    app.running = false;
    clearInterval(app.timer);
    app.timer = 0;
    setText(els.progressTitle, "程序已退出");
    setText(els.progressDetail, message || "可以关闭这个页面了。");
    setText(els.jobState, "已退出");
    els.jobState.className = "job-state";
    updateControls();
    showToast(message || "程序已退出", "error");
  }

  // -------------------------------------------------------------- polling

  async function refresh() {
    if (app.dead || app.polling) return;
    app.polling = true;
    try {
      var snap = await api("/api/state");
      app.failures = 0;
      applySnapshot(snap);
    } catch (err) {
      app.failures += 1;
      if (err.status === 403) {
        markDead("页面会话已失效，请刷新页面重新连接。");
        return;
      }
      if (app.failures >= 3) {
        markDead("无法连接本地服务，程序可能已经退出。");
        return;
      }
    } finally {
      app.polling = false;
    }
  }

  // ----------------------------------------------------------------- init

  function bind() {
    els.pickFiles.addEventListener("click", function () { pick("files"); });
    els.pickFolder.addEventListener("click", function () { pick("folder"); });
    els.addManual.addEventListener("click", addManualPaths);
    els.manualPaths.addEventListener("keydown", function (event) {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        addManualPaths();
      }
    });
    els.clearFiles.addEventListener("click", clearFiles);
    els.pickOutput.addEventListener("click", pickOutputDir);
    [els.fmtMd, els.fmtDocx, els.audioFormat, els.workers].forEach(function (el) {
      el.addEventListener("change", scheduleSettings);
    });
    els.force.addEventListener("change", updateControls);
    els.start.addEventListener("click", startJob);
    els.cancel.addEventListener("click", cancelJob);
    els.openOutput.addEventListener("click", openOutput);
    els.quit.addEventListener("click", quitApp);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) refresh();
    });
  }

  function init() {
    if (!TOKEN || TOKEN.indexOf("__V2T_") === 0) {
      markDead("页面令牌缺失，请重新打开程序。");
      return;
    }
    bind();
    updateControls();
    refresh();
    app.timer = setInterval(refresh, 900);
  }

  init();
})();
