# 视频转文字

把本地视频或音频里的说话声，转成可编辑的 Markdown / Word 文稿，并同时导出音频文件。

原生桌面窗口，不需要浏览器；全部在本机完成，不上传、不排队、不需要账号。基于 FunASR（Paraformer + FSMN-VAD + CT-Punc）做中文语音识别。

![界面截图](docs/screenshot.png)

## 能做什么

- 选择多个文件或整个文件夹，批量转写；递归读取子文件夹里的音视频。
- 导出 Markdown（`.md`）与 Word（`.docx`），同时可导出 M4A（默认）或 WAV 音频。
- 每篇文稿包含：带时间轴的逐句文稿、连续文稿、以及“数据来源与局限”。
- 已有同一来源的文稿会自动跳过；勾选“重新转写”则强制覆盖。
- 任务可取消；已完成的输出保留，未开始的不会执行。
- 转写进度、失败原因、运行日志都在界面里。

支持格式：`mp4` `mov` `mkv` `webm` `avi` `m4v` `ts` `flv` `wmv` `m4a` `mp3` `wav` `aac` `flac` `ogg` `opus` `wma`。

## 下载与安装

发布页每次打 tag 会生成两个压缩包：

| 平台 | 文件 | 说明 |
| --- | --- | --- |
| macOS（Apple Silicon） | `VideoToText-macos-arm64.zip` | macOS 14 及以上，M1/M2/M3/M4 |
| Windows 10/11（64 位） | `VideoToText-windows-x64.zip` | 解压后运行 `VideoToText.exe` |

> **Intel Mac 不支持。** PyTorch 2.14 没有 macOS x86_64 的官方轮子，语音识别引擎无法在 Intel Mac 上运行。Windows ARM 也不在支持范围内。

### macOS

1. 下载 zip，解压，把 `视频转文字.app` 拖进“应用程序”。
2. 第一次打开：在 Finder 里**右键 → 打开**，或双击后到“系统设置 → 隐私与安全性”里点“仍要打开”。
3. 应用使用 ad-hoc 签名，未做 Apple 公证，所以系统会提示“无法验证开发者”。这是正常的；它**不是“已损坏”**——签名完整性已在打包与解压后校验通过。

如果确实看到“已损坏”（通常发生在下载中断或第三方解压工具改动了文件），请重新下载；不建议关闭系统安全设置。

### Windows

1. 下载 zip，**完整解压**到任意文件夹（不要直接在压缩包里运行）。
2. 双击 `VideoToText.exe`。
3. 如果出现 SmartScreen 提示，点“更多信息 → 仍要运行”。

## 第一次运行：下载语音模型

程序本身不带模型。第一次开始转写时，会从 ModelScope 下载约 **2.1 GB** 的模型：

- Paraformer 中文语音识别（约 953 MB）
- CT-Punc 断句与标点（约 1.1 GB）
- FSMN-VAD 语音端点检测（约 4 MB）

下载只需要一次，之后可以离线使用。缓存位置：

- macOS：`~/.cache/modelscope`
- Windows：`C:\Users\<用户名>\.cache\modelscope`

要在离线机器上首次使用，可以把已下载的 `modelscope` 缓存目录复制到目标机器的同一路径。

## 使用

1. **选择素材**：点“选择视频 / 音频”选文件，或点“选择文件夹”递归读取；也可以把文件、文件夹直接拖进窗口。
2. **输出设置**：选择保存文件夹、文稿格式（Markdown / Word）、是否同时导出音频（M4A / WAV / 不导出）。
3. **开始转写**：进度面板会显示每个文件的状态；可以随时取消。
4. 完成后点“打开输出文件夹”，或点任务行里的 MD / DOCX / 音频按钮直接打开对应文件。

高级选项里可以设置同时转写的文件数（1–4）和是否强制重新转写。

输出文件命名与源文件同名；重名时自动加 `(2)` 等后缀，不会覆盖无关文件。

## 命令行（源码用户）

需要 Python 3.12、ffmpeg，并安装依赖：

```bash
git clone <repo-url>
cd video-to-text
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
```

无界面批量转写：

```bash
video-to-text transcribe "/path/to/视频目录" -o output --formats md,docx --audio m4a
```

常用参数：

- `--formats md,docx`：文稿格式；留空表示只要音频
- `--audio m4a|wav|none`：音频导出格式
- `--force`：已有文稿也重新转写

启动桌面窗口：

```bash
video-to-text
```

其他参数：`--output <目录>`（覆盖默认保存位置）、`--self-test`（安装自检）。

### 从源码打包

```bash
python packaging/fetch_ffmpeg.py          # 下载当前平台的静态 ffmpeg
pyinstaller packaging/video_to_text.spec --noconfirm --distpath dist --workpath build
```

macOS 产物是 `dist/视频转文字.app`，Windows 产物是 `dist/VideoToText/`。CI 会为 tag 自动构建并发布两个平台的 zip（见 `.github/workflows/build.yml`）。

## 隐私

- 界面是本地桌面窗口，程序不监听任何网络端口，也不会启动本地 Web 服务。
- 音视频与文稿不会离开本机。
- 唯一的联网行为是首次运行时从 ModelScope 下载模型；之后完全离线。

## 已知限制

- **只做语音识别，不做画面 OCR**：画面上的字幕、标题不会被读取。
- 语音识别未经人工校对，专有名词、同音字、人名地名可能出错；每篇文稿都附有这一说明。
- 识别结果覆盖的是“检测到人声”的片段；纯音乐、静音、噪声段不会产生文字，覆盖率会低于 100%。
- 模型以中文为主，中英混说通常可用；纯英文、强口音、多人抢话、背景噪声大的素材效果会下降。
- 没有 GPU 加速，使用 CPU。8 核 Apple Silicon 实测约为素材时长的 6–9 倍速（单文件）；并发 2 路可提高总吞吐，但更吃内存（16 GB 建议并发 1–2）。
- macOS 包只支持 Apple Silicon；Windows 包由 CI 构建，当前主力验证平台是 macOS Apple Silicon，Windows 上的长时间批量任务请在正式使用前先小批量试跑。

## 验证状态（2026-10-29）

- macOS Apple Silicon（8 核 / 16 GB）：已验证原生 Qt 窗口从源码与打包版启动、渲染；源码窗口真实 29 秒中文口播端到端（md + docx + m4a，3 段，覆盖 85%），取消任务后状态为“已取消”；打包 `.app` 自检全项通过（ffmpeg、torch / FunASR / ModelScope、多进程、音频抽取与 M4A、断句标点、Markdown、DOCX、Qt），打包版命令行真实转写结果与源码一致；zip 解压后 `codesign --verify --deep --strict` 通过，解压出的 `.app` 可启动并通过自检。
- 长时间素材：同一转写内核跑过真实 28 分钟中文音频（396 段，覆盖 98%）。
- Windows x64：已配置 `.github/workflows/build.yml`，但尚未在 GitHub Actions 实际运行，开发环境也没有 Windows 实机；首次发布前需要在 Windows 上小批量试跑。

## 开发与测试

```bash
python -m unittest discover -s tests -v
```

测试不加载模型，覆盖 ffmpeg 探测回退、断句、Markdown/DOCX 结构、配置校验，以及离屏 Qt 窗口冒烟测试（添加素材、输出格式校验、移除、设置持久化）。

## 许可

应用代码使用 MIT License，见 [LICENSE](LICENSE)。

打包产物内含第三方组件：ffmpeg 是以独立可执行文件形式分发的 GPLv2+ 构建；界面库 Qt / PySide6 以 LGPLv3 动态链接、未修改并随包分发。完整清单与许可证说明见 [NOTICE](NOTICE)，许可证全文见压缩包内的 `LICENSE.GPL-2.0.txt` 与 `LICENSE.LGPL-3.0.txt`（源码中位于 `packaging/`）。

## 致谢

- [FunASR](https://github.com/modelscope/FunASR) 与 [ModelScope](https://modelscope.cn/)：语音识别、端点检测与标点模型
- [PyTorch](https://pytorch.org/)：推理运行时
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/)：原生桌面界面
- [FFmpeg](https://ffmpeg.org/)：音频抽取与转码
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)：跨平台静态 ffmpeg 构建
