# Preparing the runtime environment (PPT → page-by-page explainer video)

This skill runs entirely locally and depends on three things: **ffmpeg**, **Python 3 + edge-tts**, and **a Chinese font**.

Run the preflight check first; it tells you in one shot which item is missing:

```bash
node "<SKILL_DIR>/scripts/precheck.mjs" --job "<JOBDIR>" --minutes <ESTIMATED_MINUTES>
```

`precheck.mjs` probes ffmpeg / ffprobe / fonts in the order `PATH → /usr/bin → /usr/local/bin → common install locations → ~/bin`, and tries `import edge_tts` on each interpreter to single out the Python one that actually works.

The preflight output looks like this (real output, paths redacted):

```
=== Preflight check ===
✅ ffmpeg     resolvable; for real availability run once through Bash: ~/bin/ffmpeg.exe -version
    ↳ ~/bin/ffmpeg.exe
✅ ffprobe
    ↳ ~/bin/ffprobe.exe
✅ CJK font
    ↳ C:/Windows/Fonts/simhei.ttf
✅ edge_tts
    ↳ ~/.workbuddy/binaries/python/versions/3.13.12/python.exe
❌ page images extract page images first (LibreOffice -> PDF + pymupdf)
    ↳ <JOBDIR>/pages
✅ disk budget 4 min ≈ 53 MB
    ↳ estimated film size

total 6 checks, 1 failed — fix them before starting
```

The last item, `page images`, is inevitably ❌ before you start work — that is precisely the first step you have to do. Once the other 5 items are all ✅, the environment is fine and you can begin.

The manual installation steps below are for when you would rather skip the preflight check.

## 1. ffmpeg (required; on PATH or passed explicitly with `--ff`)

- **Windows**: `winget install ffmpeg` / `scoop install ffmpeg` / `choco install ffmpeg`; or download the essentials build from <https://www.gyan.dev/ffmpeg/builds>, unzip it, and add `bin` to PATH.
- **macOS**: `brew install ffmpeg`
- **Linux (Debian/Ubuntu)**: `sudo apt install ffmpeg`
- Verify: `ffmpeg -version` producing output is enough.
- If you would rather not touch PATH, pass `--ff /path/to/ffmpeg --ffprobe /path/to/ffprobe` to the script.

## 2. Python 3 + edge_tts (TTS narration, no key required)

- Requires Python 3.10+.
- Install the engine: `pip install edge_tts` (Microsoft Azure's free neural voices, no account or key needed, **but synthesis requires an internet connection**).
- Verify: `python3 -m edge_tts --list-voices | grep -i xiaoxiao` (on Windows use `findstr /i xiaoxiao`) — if you can see `zh-CN-XiaoxiaoNeural`, it is working.
- Change the voice: `--voice zh-CN-YunxiNeural` (male), and so on; list them all with `--list-voices`.

> **Multiple interpreters are a common pitfall**: the `python3` on your PATH may be exactly the one without `edge_tts` installed. Let `precheck.mjs` pick one, or point directly at one with `--py <python.exe>`.

## 2b. LibreOffice and pymupdf (new in v2.0.0, for steps 0 and 1)

- **pymupdf** — required by step 1 (`pdf_to_pages.py`) to rasterize the PDF: `pip install pymupdf`. The current API is `import pymupdf`; older installs expose `import fitz`, and the script tries both.
  ⚠️ Install it into the **same interpreter** as `edge_tts`, or you end up in the half-broken state where step 0 produces a PDF and step 1 cannot read it. `precheck.mjs` reports which interpreter each one lives in.
- **LibreOffice** (`soffice`) — needed by step 0 (`to_pdf.py`) only when the source is a PPT/Word/spreadsheet: <https://www.libreoffice.org/download/>
  - If you cannot install it, save the deck as a PDF yourself (PowerPoint / WPS / any LibreOffice install elsewhere) and start at step 1 with `--input <file.pdf>`.
  - On Windows, `to_pdf.py` prefers `soffice.com` — the console build that blocks until the conversion has finished — over `soffice.exe`, the GUI launcher that returns before the file exists. It also starts an isolated profile via `-env:UserInstallation=...` so it does not fight a LibreOffice instance you already have open.

## 3. Chinese font (subtitle rendering)

- **Windows**: ships with `SimHei` (Hei), so no extra installation is needed and the scripts use it by default.
- **Linux**: install `fonts-noto-cjk` or `wqy-zenhei`, and pass `--font "Noto Sans CJK SC"` to the script (or change `Fontname` in the ASS style line as well).
- **macOS**: `PingFang SC`, or install `Noto Sans CJK SC`.

## 4. Where the page images come from (steps 0 and 1)

Since v2.0.0 the source of page images is pinned to the PDF, and that is what stops the layout from drifting:

```bash
# step 0 — only for PPT/Word/spreadsheet input; a PDF passes straight through
python "<SKILL>/scripts/to_pdf.py" --input "<deck.pptx>" --job .

# step 1 — PDF → pages/01.png … NN.png, plus source.txt for reference while writing narration
python "<SKILL>/scripts/pdf_to_pages.py" --job . --outdir pages
```

- Default 144 dpi ≈ 1920×1080; `--scale-to 1920` forces the long edge, and `--min-dpi` protects very small pages.
- Step 1 also writes `pdf/pages_meta.json` (per-page dimensions) and measures the aspect ratio of every page, warning when several ratios are mixed.
- Rather not install LibreOffice? Export the PDF by hand (PowerPoint/WPS: File → Export → PDF) and run step 1 only.

> **Do not extract page images straight from the PPT with python-pptx.** That route re-lays-out the page from the shape object model, which does not substitute fonts, re-wrap lines or correct line heights — the symptoms are shifted layout and text sitting on top of graphics. It is exactly what v2.0.0 removed.

## 5. Pitfalls in restricted sandbox environments (important)

Some Agent runtimes sandbox **Node so it cannot spawn external processes directly** (`spawnSync` / `execSync` reports `EBUSY`, or produces no output silently). This is how the skill works around it:

- Whenever you invoke `ffmpeg` / `python3` / `ffprobe`, **always run it directly from the shell** — do not run it from inside a Node script.
- The Node scripts (`gen_ass.mjs` / `gen_final.mjs` / `gen_srt.mjs`) only "read files → assemble a command string → write a file"; the `.sh` they produce is then handed to the shell to execute.
- Delete files with Node's `fs.unlinkSync` (`Remove-Item` is unreliable in some environments).
- Run any single render/concat task that takes more than 2 minutes in the background, so it does not get cut off by a foreground timeout.
