# 运行环境准备（PPT → 逐页讲解视频）

本技能纯本地运行，依赖三样东西：**ffmpeg**、**Python 3 + edge-tts**、**一款中文字体**。

先跑自检，它会一次性告诉你缺哪一项：

```bash
node "<技能目录>/scripts/precheck.mjs" --job "<JOBDIR>" --minutes <预计分钟>
```

`precheck.mjs` 按 `PATH → /usr/bin → /usr/local/bin → 常见安装目录 → ~/bin` 依次探测 ffmpeg / ffprobe / 字体，并逐个试 `import edge_tts` 挑出真正可用的 Python 解释器。下面是不想用自检时的手动装法。

## 1. ffmpeg（必须，在 PATH 或显式传 `--ff`）

- **Windows**：`winget install ffmpeg` / `scoop install ffmpeg` / `choco install ffmpeg`；或到 <https://www.gyan.dev/ffmpeg/builds> 下载 essentials 版，解压后把 `bin` 加进 PATH。
- **macOS**：`brew install ffmpeg`
- **Linux (Debian/Ubuntu)**：`sudo apt install ffmpeg`
- 验证：`ffmpeg -version` 有输出即可。
- 不想加 PATH 时，给脚本传 `--ff /path/to/ffmpeg --ffprobe /path/to/ffprobe`。

## 2. Python 3 + edge_tts（TTS 配音，免 key）

- 需 Python 3.10+。
- 安装引擎：`pip install edge_tts`（微软 Azure 免费神经语音，无需账号/密钥，**但合成时要联网**）。
- 验证：`python3 -m edge_tts --list-voices | grep -i xiaoxiao`（Windows 用 `findstr /i xiaoxiao`）能看到 `zh-CN-XiaoxiaoNeural` 即正常。
- 换音色：`--voice zh-CN-YunxiNeural`（男声）等，列全部用 `--list-voices`。

> **多解释器是常见坑**：PATH 里的 `python3` 可能正好是没装 `edge_tts` 的那个。用 `precheck.mjs` 挑，或直接 `--py <python.exe>` 指定。

## 3. 中文字体（字幕渲染）

- **Windows**：自带 `SimHei`（黑体），无需额外安装，脚本默认就用它。
- **Linux**：装 `fonts-noto-cjk` 或 `wqy-zenhei`，并给脚本传 `--font "Noto Sans CJK SC"`（或同步改 ASS 样式行的 `Fontname`）。
- **macOS**：`PingFang SC`，或装 `Noto Sans CJK SC`。

## 4. 页图怎么来（管线的第 1 步输入）

技能接收 `01.png … NN.png` 作为每页画面，三种导出方式任选：

- **PowerPoint / WPS**：文件 → 导出 → 图片（PNG），按顺序命名。
- **LibreOffice**（没装 Office 时）：
  ```bash
  soffice --headless --convert-to pdf x.pptx
  python -c "import fitz,sys; d=fitz.open('x.pdf'); [p.get_pixmap(matrix=fitz.Matrix(2,2)).save(f'{i+1:02d}.png') for i,p in enumerate(d)]"
  ```
  （本机 ffmpeg 常不带 PDF 解码器，所以走 PDF → pymupdf 抽图，而不是让 ffmpeg 直接读 PDF。）
- **已装 `ppt-explain` 技能**：`node <ppt-explain>/scripts/doc-to-pages.mjs --input x.pptx --outdir <JOBDIR>`，会一并产出 `source.txt` 文本。

## 5. 受限沙箱环境的坑（重要）

部分 Agent 运行时的沙箱**禁止 Node 直接 spawn 外部进程**（`spawnSync` / `execSync` 报 `EBUSY`，或静默无输出）。本技能的应对：

- 凡是调 `ffmpeg` / `python3` / `ffprobe`，**一律用 shell 直接跑**，不要塞进 Node 脚本里执行。
- Node 脚本（`gen_ass.mjs` / `gen_final.mjs` / `gen_srt.mjs`）只做「读文件 → 拼命令字符串 → 写文件」，产出的 `.sh` 再交给 shell 执行。
- 删文件用 Node `fs.unlinkSync`（某些环境下 `Remove-Item` 不可靠）。
- 单次渲染/拼接超过 2 分钟的任务挂后台跑，避免被前台超时掐断。
