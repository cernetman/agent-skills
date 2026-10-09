---
name: ppt-to-explainer-video-ffmpeg
description: Turn a PPT/PDF/document into a page-by-page explainer video — slide image + presenter narration + burned-in subtitles + transitions. Since v2.0.0 all input is normalized through PDF first (LibreOffice → PDF → page images), so the page layout can no longer drift. Narration is synthesized with edge-tts and the film is rendered by your local ffmpeg, with no online transcription service and no upload of your material. Supports both static per-sentence subtitles and a right-to-left rolling marquee, plus an optional title card and a freeze-frame on the last page. Use it when the user asks to "make this deck into a narrated video", "an explainer video with a voice-over", "a video of these slides with subtitles", or "record a voice-over for my courseware".
license: MIT
version: 2.0.0
author: cernetman
category: office
---

# PPT → page-by-page explainer video (local ffmpeg)

## When to use it

The user hands you a PPT/PDF/document and wants a "page-by-page explainer video with a presenter voice-over and subtitles".

**Ask for the target duration first** (a 4-minute highlight cut ≈ 1000 characters of narration, at roughly 250 characters/minute for Chinese speech).

**Don't use it for**: fully offline or air-gapped machines (edge-tts needs network), scanned decks with no text layer, projects that must preserve the original PPT animations, or multilingual narration.

## Architecture: three stages (refactored 2026-10-02, with measurements)

The old approach was "bake subtitles into each segment, then chain N−1 levels of `xfade`". On 50 pages that measured **65 s + 63 s = 128 s**, and every added `xfade` level re-encoded the whole film, degrading quality generation after generation.

The new approach decouples **subtitle burn-in** from **transition assembly**:

```
① segment render (no subtitles, parallel j=4)  →  seg/NN.mp4  + durations2.txt
② -f concat -c copy hard cut                   →  master.mp4 (0 re-encodes)
③ single pass burning all.ass                  →  final.mp4 (the only full-film re-encode)
```

### Benchmarks (50 pages / 1920×1080 / 30fps, Windows 11 test machine)

| Stage | Old architecture | New (medium) | New (veryfast) |
|---|---|---|---|
| Segment render | 65 s (serial, subtitles inside) | 41.7 s (parallel j=4, no subtitles) | 41.7 s |
| Assembly | 63 s (49-level `xfade`) | 1.4 s (`-c copy` hard cut) | 1.4 s |
| Subtitle burn | inside the segment render | 47.5 s (crf20 medium) | 34.8 s (crf20 veryfast) |
| **Total** | **128 s** | **90.6 s (−29%)** | **77.9 s (−39%)** |

**Parallelism is the single biggest win**: with subtitles off, `--j 1` takes 58.8 s versus `--j 4` at 41.7 s (**−29%**).

### Full-film regression (2026-10-02, a real 50-page corporate deck)

| Metric | Old film | New film | Note |
|---|---|---|---|
| Duration | 464.5 s | 492.1 s | A hard cut spends no time on transitions; each page follows its narration length |
| Size | 119.5 MB | 47.9 MB | **Only 40% of the old output** |
| Bitrate | 2059 kbps | 778 kbps | The content is mostly static text and diagrams; text is sharp at this bitrate in practice |
| Total render time | 128 s | 42.1 s (segments) + 1.4 s (assembly) + 49 s (burn) ≈ **93 s (−27%)** | |
| Audio | aac ✓ | aac ✓ (not lost after `concat -c copy`) | |

Sampled frames passed review: a 3 s title card (plain text company name), a mid-film rolling subtitle actually rolling, a 3 s freeze on the last page, no black frames and no audio/video drift.

**Bonus**: `master.mp4` is a subtitle-free master — changing the title card or switching subtitle form (static ↔ rolling) requires **no re-recording and no re-rendering of segments**, only another burn. A 3 s title card is appended with `-c copy`, without re-encoding the film.

> To keep the cross-fade look: give every segment 0.5 s of extra headroom on both ends, or use `--mode xfade` on the final step (the legacy flow).

## Prerequisites

Run the preflight check first instead of charging ahead:

```bash
node "<SKILL_DIR>/scripts/precheck.mjs" --job "<JOBDIR>" --minutes <estimated minutes>
```

- **ffmpeg / ffprobe / CJK font are all auto-detected, with no machine paths hard-coded**: `precheck.mjs` searches `PATH → /usr/bin → /usr/local/bin → common install locations → ~/bin`, then on Windows `C:/Windows/Fonts/simhei.ttf`, on Linux WenQuanYi/Noto CJK, on macOS PingFang. **It runs on another machine unchanged**; override with `--ff` / `--font` / `--ffprobe` when needed.
- **The Python interpreter is a trap**: the `python3` on `PATH` may be a version **without `edge_tts`** (a real case: 3.14.3 did not have it, 3.13.12 did). `precheck.mjs` tries `import edge_tts` against every candidate (`where python` plus each managed Python version) and tells you which one works; you can also pass `--py <python.exe>`.
- **New in v2.0.0 — steps 0 and 1 need two more dependencies**:
  - **LibreOffice** (`soffice`): only needed when the source is a PPT/Word/spreadsheet. You can skip it entirely by saving a PDF yourself and starting at step 1. <https://www.libreoffice.org/download/>
  - **pymupdf** (`pip install pymupdf`): required to rasterize the PDF. The current API is `import pymupdf`; older installs expose `import fitz`, and the script tries both.
  - ⚠️ **`pymupdf` and `edge_tts` must be installed in the same interpreter**, or you get the half-broken state where step 0 produces a PDF and step 1 cannot read it. `precheck.mjs` reports which interpreter each one lives in.
- **Page images come from the PDF, not from ffmpeg**: ffmpeg usually ships without a PDF decoder, which is why rasterizing is done by pymupdf.

## Input chain: PPT → PDF → page images → video (mandatory since v2.0.0)

```
<file.pptx>  ──[0] to_pdf.py (LibreOffice)──►  pdf/source.pdf
                                                 │
<file.pdf>  ─────────────────────────────────────┤  passes straight through, no conversion
                                                 ▼
                                            [1] pdf_to_pages.py (pymupdf)
                                                 ▼
                                        pages/NN.png + source.txt
                                                 ▼
                                        [2–7] narration / render / subtitles / assemble  ← unchanged
```

**Why a PDF has to sit in the middle (this is the entire motivation for v2.0.0)**

The old flow fed the deck straight into page extraction and relied on a library such as `python-pptx` to re-lay-out the page from the shape object model. Such libraries read coordinates only: they do not substitute fonts, do not re-wrap lines, and do not correct line heights. The moment a text box is smaller than its text, a font is missing, or a master placeholder goes unrendered, the extracted image no longer matches what PowerPoint shows — the symptoms are **shifted layout, text on top of graphics, misplaced elements**.

Once the deck is a PDF, LibreOffice's full layout engine fixes the layout **once and for all** (a PDF records absolute coordinates), and step 1 only rasterizes each page. There is **no re-layout step left**, so the drift disappears at the root.

**The cost**: one extra conversion (a 50-page deck measured 25–40 s on the Windows test machine). What you get back is page images whose aspect ratio is identical across the whole deck (measured 1921×1080 for all 50), so the `scale`+`pad` in `render_all.py` no longer produces black bars.

### Supported inputs

| Input | What step 0 does |
|---|---|
| `.pptx / .ppt` | LibreOffice converts to PDF (Impress engine) |
| `.docx / .doc / .rtf / .odp` | LibreOffice converts to PDF |
| `.pdf` | **Passes straight through**: registered as-is, LibreOffice is never touched |
| `.xlsx / .xls` | LibreOffice converts to PDF (one page per sheet; use with care) |

## The pipeline (8 steps: 0 transcode → 7 verify)

### 0. Convert to PDF (new in v2.0.0; required for PPT/Word)

```bash
"<your python.exe>" "<SKILL>/scripts/to_pdf.py" --input "<file.pptx>" --job .
```

- Produces `pdf/source.pdf`, plus `pdf/source.json` recording the origin, the page count and the elapsed time, so you can later trace which file and which page an image came from.
- **Idempotent**: it skips when the output is not older than the source, and re-converts automatically once the deck changes. `--force` overrides that.
- **It never papers over a failure**: soffice not found, a non-zero exit, exit 0 with no output, a timeout, or a zero-page result — each is reported with the next action to take, and **no half-finished artifact is ever produced**. This step is the foundation of the pipeline: no PDF, no video. Do not try to skip it.
- A job that already has its PDF does **not** need LibreOffice installed; go straight to step 1.
- Failure codes and troubleshooting are in "Step 0 failure handling" below.

### 1. PDF → page images + text

```bash
"<your python.exe>" "<SKILL>/scripts/pdf_to_pages.py" --job . --outdir pages
```

- The input is **the PDF only** (since v2.0.0 the source of page images is pinned down, and that is what eliminates the drift).
- Produces `01.png…NN.png` + `source.txt` (the per-page text, handy while writing narration) + `pdf/pages_meta.json` (per-page dimensions).
- Default 144 dpi ≈ 1920×1080; `--scale-to 1920` forces the long edge, and `--min-dpi` protects very small pages.
- **Aspect-ratio check**: the script measures the aspect ratio of every page and, when several ratios are mixed, **warns without blocking** (a source deck may legitimately mix them) — but it names exactly which pages differ.
- ⚠️ ffmpeg usually ships without a PDF decoder, which is why this step uses pymupdf instead.

> **Do not fall back to extracting page images straight from the PPT with python-pptx** — that is precisely the drift v2.0.0 exists to eliminate.
> The `ppt-explain/scripts/doc-to-pages.mjs` that older documentation referenced is **deprecated**: that skill was not installed here, so every run improvised a different workaround, and the resulting page images disagreed in size and ratio. v2.0.0 replaces it with `pdf_to_pages.py` from this repository.

### 2. Write the narration (one `vo3/NN.txt` per page)

Conversational and TTS-friendly; **keep Arabic numerals as digits**. Total characters ≈ target seconds × 4.2 (for Chinese narration). 45–70 characters for cover/transition pages, 75–100 for key-point pages. **Sanity-check the character count first (±20%)**.

### 3. Voice-over + subtitles in one step (`gen_sentence_ass.py`)

```bash
"<your python.exe>" "<SKILL>/scripts/gen_sentence_ass.py" --job . --in vo3 --out mp3 \
    --assdir ass --bounds bounds_cache.json --mode scroll --size 60 --y 900
```

- **A single stream both writes the mp3 and collects the `SentenceBoundary` events**, so they are in sync by construction — no second TTS pass. The boundaries land in `bounds_cache.json`, so switching subtitle form later does not re-record.
- Existing `NN.mp3` files are skipped automatically (use `--force` to re-record).
- Outputs `mp3/NN.mp3` + `ass/NN.ass` + `bounds_cache.json`.

### 4. Segment rendering in parallel (`render_all.py`)

```bash
"<your python.exe>" "<SKILL>/scripts/render_all.py" --job . --seg seg --rows durations.json \
    --durations-out durations2.txt --no-sub --j 4 --crf 23 --preset veryfast --tail-freeze 3.0
```

**Produce `durations.json` first** — `render_all.py` only reads it, it **never derives it**. It is a per-page duration table, where `dur` is the **real duration** of `mp3/NN.mp3` (measure it with `ffprobe`, do not sum the bounds: trailing TTS silence is part of the on-screen duration too):

```bash
for f in mp3/*.mp3; do
  echo "$(basename "$f" .mp3) $(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f")"
done
```

`--rows` takes this JSON shape:

```json
[{"page": 1, "dur": 11.736}, {"page": 2, "dur": 10.872}]
```

Or generate it in one line of Python (on Windows use an absolute path for `ffprobe`, or the bare name without `.exe`):

```bash
python -c "import json,glob,os,subprocess as sp;rows=[{'page':int(os.path.basename(p)[:2]),'dur':round(float(sp.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',p],capture_output=True,text=True).stdout.strip()),3)} for p in sorted(glob.glob('mp3/*.mp3'))];json.dump(rows,open('durations.json','w'),ensure_ascii=False,indent=1);print(rows)"
```

Skip it and `render_all.py` reports the missing file along with this format description (not a bare stack trace).

- `--no-sub` (the default): segments carry no subtitles, which is what enables the three-stage flow.
- `--tail-freeze 3.0`: extra freeze on the last page.
- Produces `seg/NN.mp4` + `durations2.txt` (`NN=seconds`).
- A missing page image or voice-over file is reported by name, never silently skipped.

### 5. Whole-film subtitles (`gen_film_ass.py`)

```bash
"<your python.exe>" "<SKILL>/scripts/gen_film_ass.py" --job . --durations durations2.txt \
    --bounds bounds_cache.json --out all.ass --mode scroll --size 60 --y 900 --t 0
```

Timeline: **page i starts at Σ_{j<i} (dur_j − T)**, where `T` comes from `--t` (default 0.5).

⚠️ **`T` must match the actual transition mode, or subtitles drift cumulatively**:

| Film mode | Pass | Why |
|---|---|---|
| `--mode concat` (hard cut, **the three-stage default**) | **`--t 0`** | The concat spends no overlap, so page i really starts at Σ dur_j |
| `--mode xfade` (cross-fade) | `--t 0.5` (the default) | Each transition consumes 0.5 s of overlap |

Measured cost of forgetting `--t 0` on a hard cut (3-page sample): the picture turns the page at 11.736 s / 22.608 s, but the subtitles are already in place at 11.236 s / 21.608 s — **0.5 s early per page, 24.5 s early by page 50, with no error reported at all**. With `--t 0` the ASS starts line up exactly with the picture boundaries (0 / 11.736 / 22.608).

`--intro 2.5` is for the case where a title card has already been prepended.

### 6. Assemble the film (`gen_final.mjs`)

```bash
node "<SKILL>/scripts/gen_final.mjs" --job . --mode concat --seg seg --ass all.ass \
    --out final.mp4 [--intro intro/intro.mp4 --intro-dur 3.0]
```

Then **run the `render_final.sh` it writes** with your shell.

### 7. Verify and deliver

```bash
ffprobe -v error -show_entries format=duration,size -of default=nw=1 final.mp4
ffmpeg -y -ss <mid-film seconds> -i final.mp4 -frames:v 1 -update 1 -q:v 2 _check.png
```

**Look at the frame** to confirm the subtitles neither overflow nor cover anything. Then produce a standalone subtitle file:

```bash
node "<SKILL>/scripts/gen_srt.mjs" --job . --bounds bounds_cache.json --intro 2.5
```

Finally: copy the film and the srt to the user's desktop and present them.

## Script reference

| Script | Language | Purpose | Main parameters |
|---|---|---|---|
| `precheck.mjs` | node | Preflight environment check (ffmpeg/ffprobe/font/edge_tts/pymupdf/LibreOffice/PDF/page images/disk budget) | `--job --ff --font --py --pdf --soffice --minutes` |
| `to_pdf.py` | py | **v2.0.0** — step 0: normalize PPT/Word/spreadsheet to PDF via LibreOffice headless | `--input --job --force --clean --timeout --soffice` |
| `pdf_to_pages.py` | py | **v2.0.0** — step 1: rasterize the PDF into `pages/NN.png` + `source.txt` with pymupdf | `--job --outdir --scale-to --min-dpi --pages` |
| `gen_sentence_ass.py` | py | Voice-over + per-sentence/rolling subtitles (merges the old steps 3 and 4) | `--in --out --assdir --bounds --mode --voice --rate --size --y --force` |
| `render_all.py` | py | Parallel segment rendering + duration table export | `--seg --rows --durations-out --j --no-sub --burn-sub --crf --preset --tail-freeze` |
| `gen_film_ass.py` | py | Whole-film ASS (absolute timeline, supports scroll/static) | `--durations --bounds --txt-dir --out --mode --size --y --w --h --intro --t` |
| `gen_final.mjs` | node | Assemble the film (three-stage concat / legacy xfade) | `--mode --seg --ass --durations --out --master --intro --intro-t --preset --crf --transition` |
| `gen_ass.mjs` | node | Per-page static ASS (legacy flow compatibility) | `--job --outdir --size --font --border --align --mv --mode` |
| `gen_srt.mjs` | node | Standalone SRT (sentence level by default, with title-card offset) | `--durations --bounds --src-dir --out --intro --t --source` |

## Key parameters at a glance

| Item | Value |
|---|---|
| Frame size | `--w 1920 --h 1080` (landscape) / `1080 1920` (portrait) |
| Frame rate | 30 |
| Transition | `xfade fade 0.5s` + `acrossfade 0.5s` (legacy `--mode xfade`); the new architecture uses a hard cut plus the subtitle timeline |
| Subtitles (static per sentence) | SimHei 40–46px, white text + **BorderStyle 3** (`&HCC000000` translucent black background), Alignment=2, MarginV=90 |
| Subtitles (rolling marquee) | SimHei 60px, white text with black outline, `\an7\q2` + `WrapStyle: 2`, `\move(screen width, Y, −text width×1.06, Y, 0, that page's narration in ms)` |
| Narration voice | `zh-CN-XiaoxiaoNeural` (male: `zh-CN-YunxiNeural`) |
| Speech-rate calibration | measured ≈4.5 characters/s at Xiaoxiao's default; ≈4.8 characters/s with `--rate +11%` |
| Page extraction | this machine's ffmpeg **has no PDF decoder** → LibreOffice + pymupdf |

## The three subtitle forms (do not mix them up)

| Form | Key settings | Use it for |
|---|---|---|
| **Static, per sentence** | `WrapStyle: 0`, multiple `Dialogue` lines cut at sentence boundaries | Regular explainers, information pages |
| **Rolling marquee** | `\q2` + `WrapStyle: 2` + `\move` | Demos where the subtitle should "travel with the voice" |
| **Portrait hard subtitles** | SimHei 62px, Alignment=2, MarginV≈240 | A 1080×1920 storyboard that carries its own bottom subtitle bar |

⚠️ **`\q1` is not "no wrapping"!** `\q1` is the end-of-line wrapping mode; libass still wraps long unspaced text to the screen width (measured: a 25-character line stacked into 3 lines). Rolling subtitles must use `\q2` **and** the header `WrapStyle: 2` as a belt-and-braces pair. Only static per-sentence subtitles use `WrapStyle: 0` (which is what you want there, since it auto-wraps).

## Environment notes (this skill depends on these repeatedly)

- **Node spawning external processes can be blocked by a sandbox** (EBUSY / no output) → always call ffmpeg and Python **through your shell tool**, never from inside a Node script. Node scripts should only read files, build command strings and write files.
- ffmpeg / python / ffprobe run fine from the shell; give long jobs the sandbox escape your runtime offers.
- **Anything that renders or assembles for more than 2 minutes should go to the background**, or a foreground timeout will kill it.
- **A drive-letter colon cannot be escaped inside an ffmpeg filter on Windows**: `subtitles='C\:/x/01.ass'` fails with `Unable to parse "original_size"` → `cd` into the directory and use the relative name `subtitles='01.ass'` (`-i` inputs may still use absolute paths).
- **Delete files with Node's `fs.unlinkSync`** (`Remove-Item` is unreliable in some environments).
- On some shells running an external binary fails with a sandbox bookkeeping error; re-running the identical command usually recovers, and dropping a `VAR=...;` prefix helps.

## Pitfalls (in the order they bit us)

1. **Multi-line text breaks the ASS file**: splicing a raw `\n` into a `Dialogue` line leaves the second line without a `Dialogue:` header, libass fails to parse it, and **the whole subtitle for that page disappears while the render still reports success**. Fix: escape each line, then join with a literal `\N`. **The order matters** — joining first and escaping afterwards turns `\N` into a literal backslash followed by the letter N.
2. **Style defaults matter**: `BorderStyle=1` (outline only) gets swallowed on pages with a coloured background → use **`BorderStyle 3` + `BackColour &HCC000000`** for long films.
3. **`bounds_cache.json` keys may be `"1"` or `"01"`**: a direct `cache.get("01")` silently misses, and **the first 9 pages (01–09) lose their subtitles entirely**. Probe both spellings. This bug also existed separately in `gen_film_ass.py`, where the rolling mode masked it by falling back to `vo3/NN.txt` while the static mode produced a film with no subtitles at all.
4. **edge-tts 7.x emits `SentenceBoundary`, not `WordBoundary`**; the fields are `{type, offset, duration, text}` with offset/duration in **100 ns units** (seconds = ÷10,000,000). Writing `WordBoundary` never matches and silently yields zero events.
5. **`\q1` is not "no wrapping"** (see above).
6. **This machine's ffmpeg has no PDF decoder** → go through LibreOffice + pymupdf.
7. **`zoompan` eats the input-side `-t`**: `-loop 1 -t 3.0 -i card.png` actually yields 2.5 s → **`-t` must go on the output side** (after `-vf`) to get exactly 3.0 s.
8. **`xfade` offsets must be computed from measured segment durations** (`cum − k*T`), otherwise you get "first input is not long enough"; if the `filter_complex` exceeds 1400 characters, write it into a `.sh` file and run that instead of hand-building the argument.
9. **Subtitle collisions must be checked on sampled frames**: text-dense pages and closing contact pages (with their own black-on-white phone-number bar) are the worst offenders — the `BorderStyle 3` translucent background solves the text-dense case.
10. **Rolling subtitles use the whole page's text**, not just `ev[0][0]` (which leaves only the first sentence rolling).
11. **The title card in a `concat -c copy` must carry a real-length silent audio track**, at least as long as the card. The trap: pairing `-shortest` with a 3 s card and a 2 s silence truncates the card to 2 s without any error. Correct approach:
    ```bash
    ffmpeg -y -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -t 3 -c:a aac silent.m4a   # build a full-length silence first
    ffmpeg -y -loop 1 -i card.png -i silent.m4a -vf "zoompan=... ,format=yuv420p" \
        -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -r 30 -c:a copy -t 3 intro3.mp4        # -t on the output side, not -shortest
    ```
12. **Relative paths in a concat list resolve against the list file's own directory**. Writing `file 'bench3/seg/01.mp4'` into `bench3/list.txt` resolves to `bench3/bench3/…` and fails with `Invalid argument`. **Always put the list in the project root** and write segment paths as `bench3/seg/01.mp4`.
13. **The quality bottleneck of the finished film is the CRF of step ③ (the subtitle burn), not the segment CRF.** On a like-for-like 5-page sample, segments at crf18 versus crf23 changed the final size by only 7.8% (4.71 vs 4.38 MB) — step ③ re-encodes anyway, which flattens the segment compression. Taking the whole film from crf20 to crf17 grew it by 21% (47.9 → 58.1 MB) with almost no visible difference on the same frame. **778 kbps is plenty for a text-and-diagram film; do not chase bitrate numbers by crushing the CRF.**
14. **`execSync` from a Node script hangs with EBUSY when it calls ffprobe/ffmpeg** → measure durations and sizes, and sample frames, from the shell; Node should only read files, build command strings and write files.
15. **`--t` must match the film mode, or subtitles drift page by page** (the most insidious one in this project). `gen_film_ass.py` builds its timeline as `page i starts at Σ_{j<i}(dur_j − T)` with `T` defaulting to **0.5** (compensation for `xfade` transitions). But the three-stage film uses `--mode concat`, a **hard cut**, which has no overlap at all → subtitle page i lands (i−1)×0.5 s early. Measured on 3 pages: the picture turns at 11.736 s / 22.608 s while the subtitles are ready at 11.236 s / 21.608 s; **by page 50 that is 24.5 s early**, with zero errors raised. Fix: always pass `--t 0` for hard-cut films (the ASS then starts at 0 / 11.736 / 22.608, exactly matching the picture boundaries).
16. **`durations.json` is never generated for you.** `render_all.py`'s `--rows` is a required input, yet no script in the 7-step pipeline produces it → a direct run fails on a missing file. Measure the real duration of `mp3/NN.mp3` with `ffprobe` and build it yourself (step 4 has a ready-made command). **Do not substitute a sum of bounds**: trailing TTS silence counts towards the on-screen duration.
17. **The fractional part of an ASS timestamp is centiseconds, not milliseconds** (the most severe bug in this project: it misaligns the whole subtitle track). `tss()` printed the millisecond remainder (0–999) with `%02d`, which emits three digits once the value reaches 100: `.100` / `.500` / `.999`. libass parses the fraction as centiseconds → the **fraction is inflated 10×**: an event declared to start at `0:00:00.100` only appeared on screen at **1.0 s**, and `.999` was off by 9 s. The error jitters with each timestamp's millisecond digits (0–9 s) and **nothing ever reports an error**. How to detect it: render the ASS alone over a black background, position it at an exact time with `setpts=PTS+T/TB` and count white pixels — if a declared `0.100` only appears at 1.0 s, you have it. Fix: compute centiseconds and always print two digits — `cs = round(s*100)` followed by `"%d:%02d:%02d.%02d"`.
18. **The rolling and static modes need separate ASS headers**; sharing one trips two bugs at once. Static subtitles stop wrapping (`WrapStyle: 2` is the rolling mode's "do not auto-wrap") and run off the right edge; and hard-coding `PlayResX/PlayResY` in the header renders `--w/--h` inert (portrait arguments silently do nothing). Correct: rolling uses `WrapStyle 2` + `Alignment 7` + `MarginV y`; static uses `WrapStyle 0` + `Alignment 2` + `MarginV h−y`.

19. **A UTF-8 BOM in the narration files leaks into the audio and the subtitles**: read `vo3/NN.txt` with `utf-8-sig`, not plain `utf-8`. `str.strip()` does not remove U+FEFF, so an invisible character becomes the first character of every subtitle built from a page file — and Notepad and several Windows editors write that BOM by default.
20. **Extracting page images straight from a PPT always drifts** (the root cause of the v2.0.0 upgrade): `python-pptx` reads shape coordinates only — it does not substitute fonts, re-wrap lines or correct line heights, so the moment a text box is smaller than its text or a font is missing, the layout stops matching PowerPoint. **Convert to PDF first** and let the layout engine fix the absolute coordinates once.
21. **On Windows, calling `soffice.exe` returns "exit 0" before the file exists**: `soffice.exe` is the GUI launcher and returns immediately; `soffice.com` is the console build that blocks until the conversion has finished. `to_pdf.py` probes `soffice.com` before `soffice.exe` — **do not change it back to `soffice.exe` only**. LibreOffice also writes asynchronously, so the script additionally waits until the file size has been stable for 1.2 s.
22. **LibreOffice fights with an instance the user already has open**: sharing one user profile makes it refuse the conversion outright (sometimes while still returning 0). `to_pdf.py` starts an isolated profile with `-env:UserInstallation=file:///<temp dir>` and **always deletes it afterwards** (it is large; leaving it behind dirties the project directory).
23. **`soffice` reports "exit 0 with no output" for encrypted, protected or corrupt documents**: no error, and no PDF either. `to_pdf.py` detects that case specifically and offers three concrete ways out instead of letting it slide by.
24. **`pymupdf` and `edge_tts` must live in the same interpreter**: installing them into two different Pythons produces the broken chain where step 0 succeeds and step 1 dies with `ModuleNotFoundError`. `precheck.mjs` reports which interpreter each one is in.
25. **The intermediate PDF is kept by default**: `pdf/source.pdf` stays, so you can re-extract pages, check the page count and trace the origin; remove it with `to_pdf.py --clean` once you are satisfied. **The LibreOffice temporary profile, by contrast, must always be deleted** — do not confuse the two.

## Step 0 failure handling (PPT → PDF)

`to_pdf.py` reports five classes of failure separately and **never falls back to "extract the PPT directly"** (that would invite the drift straight back):

| Symptom | What the script does | What you do |
|---|---|---|
| soffice not found | Lists the paths it probed, plus the download link | Install LibreOffice; or save a PDF yourself and pass `--input x.pdf`; or point at it with `--soffice <full path>` |
| soffice exits non-zero | Prints the last 600 characters of stderr | Act on the error; the usual cause is the file being locked by an open Office/WPS window |
| Exit 0 but no PDF | Says outright that the conversion did not succeed | The document is probably encrypted, protected or corrupt — save a fresh copy |
| Timeout (300 s by default) | Kills the process and reports it | For a large deck with many images, raise it with `--timeout 600` |
| Zero pages produced | **Deletes the artifact** and reports the failure | An empty PDF would silently produce a zero-segment empty video, so it has to be stopped here |

## Version history

| Version | Date | Changes |
|---|---|---|
| **2.0.0** | 2026-10-07 | **Major upgrade (pipeline restructure).** ① New step 0 `to_pdf.py`: PPT/Word → PDF via LibreOffice headless, so layout is fixed in the PDF and **page drift is eliminated at the root**; ② new step 1 `pdf_to_pages.py`: PDF → page images, replacing the `ppt-explain/doc-to-pages.mjs` that was never installed, with the input pinned to PDF; ③ `precheck.mjs` gained four checks (soffice / pymupdf / source PDF / page images), nine in total; ④ the pipeline grew from 7 to 8 steps, while steps 2–7 (narration → voice-over → render → subtitles → assemble → verify) keep their logic and parameters **completely unchanged** — verified by running the downstream six scripts unmodified against a real 50-page deck. |
| 1.1.0 | 2026-10-02 | Three-stage architecture (segment render → `-c copy` hard cut → single subtitle burn), 128 s → 78–93 s on 50 pages; path parameters completed and missing-file errors turned into readable messages. |

## Final words

The asset here is the 25 pitfalls above, the three-stage architecture and the PPT → PDF → video input chain, not the scripts themselves. Run `precheck.mjs` before touching any script — most "it won't run" cases are environment problems, not pipeline problems.

Environment installation (ffmpeg / edge-tts / CJK fonts / LibreOffice / pymupdf) is covered in `references/setup.md`; the version history is in the table above and in `CHANGELOG.md` at the repository root.
