---
name: ppt-to-explainer-video-ffmpeg
display_name: PPT 转逐页讲解视频（ffmpeg 本地版）
display_name_en: PPT to Page-by-Page Explainer Video (Local ffmpeg)
description: 把 PPT/PDF/文档做成「逐页讲解视频」（页图 + 讲师旁白 + 硬字幕 + 转场），调用 edge-tts 合成中文旁白，用本机 ffmpeg 渲染，不依赖任何在线转写服务、不上传素材。支持静态逐句字幕与从右往左滚动跑马灯两种形态，可加片头卡片与末页定格。当用户说「把这份 PPT 做成讲解视频/讲课视频/带旁白的视频」「配字幕的逐页视频」「给课件配个口播」时使用。
description_zh: 用本机 ffmpeg 把 PPT/PDF 逐页转成带 AI 旁白和硬字幕的讲解视频，全部离线渲染，无需在线转写服务。
description_en: Turn a PPT/PDF into a page-by-page explainer video with AI narration and burned-in subtitles, rendered fully locally with ffmpeg.
version: 1.1.0
author: zhangjw
license: MIT
category: office
agent_created: true
---

# PPT → 逐页讲解视频（ffmpeg 本地版）

## 何时用
用户给一份 PPT/PDF/文档，要「逐页讲解视频 + 讲师旁白 + 字幕」。
**目标时长先问清**（如 4 分钟精华版 ≈ 1000 字旁白，按 250 字/分钟折算）。

**别用它**：离线/内网（edge-tts 要联网）、扫描件无文本 PPT、要保留原 PPT 动画、多语种。

## 架构：三段式（2026-10-02 重构，性能实测）

旧做法是「每段各烧各的字幕 → 套 N-1 级 xfade 拼接」。50 页实测 **65s + 63s = 128s**，而且每加一级 xfade 都重编一遍全片、像素一代代掉质量。

新做法把**字幕烧录**和**转场拼接**解耦：

```
① 段渲染(不带字幕,并行 j=4)  →  seg/NN.mp4  +  durations2.txt
② -f concat -c copy 硬切     →  master.mp4（0 重编码）
③ 单遍烧 all.ass             →  成片.mp4（唯一一次全片重编码）
```

### 性能实测（50 页 / 1920×1080 / 30fps，Windows 11 测试机）

| 环节 | 旧架构 | 新架构（medium 定稿） | 新架构（veryfast 定稿） |
|---|---|---|---|
| 段渲染 | 65 s（串行、段内烧字幕） | 41.7 s（并行 j=4、不烧字幕） | 41.7 s |
| 拼接 | 63 s（49 级 xfade） | 1.4 s（`-c copy` 硬切） | 1.4 s |
| 烧字幕 | 含在段渲染里 | 47.5 s（crf20 medium） | 34.8 s（crf20 veryfast） |
| **合计** | **128 s** | **90.6 s（-29%）** | **77.9 s（-39%）** |

**并行是最大单项收益**：同样不烧字幕，`--j 1` 58.8 s vs `--j 4` 41.7 s（**-29%**）。

### 整片回归（2026-10-02，某企业 50 页实片对比）

| 指标 | 旧架构成片 | 新架构成片 | 说明 |
|---|---|---|---|
| 时长 | 464.5 s | 492.1 s | 硬切不吃转场时间，各页按语音长度走 |
| 体积 | 119.5 MB | 47.9 MB | **只有旧版 40%** |
| 码率 | 2059 kbps | 778 kbps | 画面以静态图文为主，此码率实测文字清晰 |
| 渲染总耗时 | 128 s | 42.1 s（段渲染）+ 1.4 s（拼接）+ 49 s（烧字幕）≈ **93 s（-27%）** | |
| 音频 | aac ✓ | aac ✓（concat `-c copy` 后未丢） | |

回归抽帧抽查通过：片头 3s（纯文字公司名）、中段滚动字幕在滚、末页定格 3s、无黑屏/音画错位。

**额外收益**：`master.mp4` 是无字幕母版——改片头、换字幕版（静态↔滚动）都**不必重新配音、不必重渲段**，只重烧一遍；加 3 秒片头走 `-c copy` 直拼，不用重编整片。

> 想保留交叉淡入的观感：给每段多渲 0.5s 前后余量，或最后一步用 `--mode xfade`（兼容旧流程）。

## 环境前提（本机已具备）

先跑自检，别一上来就硬干：

```bash
node "<技能目录>/scripts/precheck.mjs" --job "<JOBDIR>" --minutes <预计分钟>
```

- **ffmpeg / ffprobe / 中文字体全部自动探测，不写死任何机器路径**：`precheck.mjs` 按 `PATH → /usr/bin → /usr/local/bin → 常见安装目录 → ~/bin` 依次找，Windows 上还会找 `C:/Windows/Fonts/simhei.ttf`、Linux 找文泉驿/Noto CJK、macOS 找 PingFang。**换机器照样能跑**，需要时用 `--ff` / `--font` / `--ffprobe` 显式指定。
- **Python 解释器有坑**：PATH 里的 `python3` 可能是**没装 edge_tts** 的那个版本（本机 3.14.3 就没装，3.13.12 才装着）。`precheck.mjs` 会把候选解释器（`where python` + 托管 python 各版本）逐个试一遍 `import edge_tts`，挑中能用的那个告诉你；也可 `--py <python.exe>` 直给。
- 页图来源：**ffmpeg 常不带 PDF 解码器** → 走 LibreOffice 转 PDF + pymupdf 抽图。

## 管线（7 步）

### 1. 取页图 + 文本
优先复用 `ppt-explain` 专家脚本：
```bash
node "<skills>/ppt-explain/scripts/doc-to-pages.mjs" --input "<file.pptx>" --outdir "<JOBDIR>"
```
产出 `01.png…NN.png` + `source.txt`。装不上就退：WPS/Office 导出，或 python-pptx + LibreOffice（pymupdf 抽 1920×1080）。

### 2. 写旁白（每页一个 `vo3/NN.txt`）
口语化、TTS 友好：**数字保留阿拉伯数字**。总字数 ≈ 目标秒数 × 4.2。封面/过渡页 45-70 字，要点页 75-100 字。**先做字数自检（±20%）**。

### 3. 配音 + 字幕（一步做完，脚本 `gen_sentence_ass.py`）
```bash
"<你的python.exe>" "<技能>/scripts/gen_sentence_ass.py" --job . --in vo3 --out mp3 \
    --assdir ass --bounds bounds_cache.json --mode scroll --size 60 --y 900
```
- **一次流里既写 mp3 又收 `SentenceBoundary` 边界**，天然同步，不用调两次 TTS；边界落成 `bounds_cache.json`，后面换字幕版不再配音。
- 已有 `NN.mp3` 自动跳过（加 `--force` 强制重配）。
- 输出 `mp3/NN.mp3` + `ass/NN.ass` + `bounds_cache.json`。

### 4. 分段渲染（并行，脚本 `render_all.py`）
```bash
"<你的python.exe>" "<技能>/scripts/render_all.py" --job . --seg seg --rows durations.json \
    --durations-out durations2.txt --no-sub --j 4 --crf 23 --preset veryfast --tail-freeze 3.0
```

**先把 `durations.json` 备好** —— `render_all.py` 只读它，**不会自己算**。它是逐页时长表，`dur` 取 `mp3/NN.mp3` 的**真实时长**（用 `ffprobe` 量，别拿 bounds 累加：TTS 尾部静音也占画面时长）：

```bash
for f in mp3/*.mp3; do
  echo "$(basename "$f" .mp3) $(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f")"
done
```

`--rows` 吃的是这个 JSON 格式：

```json
[{"page": 1, "dur": 11.736}, {"page": 2, "dur": 10.872}]
```

一行 Python 直接生成（Windows 上 `ffprobe` 换成绝对路径或不带 `.exe` 的裸名）：

```bash
python -c "import json,glob,os,subprocess as sp;rows=[{'page':int(os.path.basename(p)[:2]),'dur':round(float(sp.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',p],capture_output=True,text=True).stdout.strip()),3)} for p in sorted(glob.glob('mp3/*.mp3'))];json.dump(rows,open('durations.json','w'),ensure_ascii=False,indent=1);print(rows)"
```

漏了它，`render_all.py` 会直接报缺文件并重复上面这段格式说明（不是裸堆栈）。
- `--no-sub`（默认）：段不带字幕，走三段式。
- `--tail-freeze 3.0`：最后一页尾部定格。
- 产出 `seg/NN.mp4` + `durations2.txt`（`NN=秒`）。
- 缺页面图/配音会直接报是哪个文件，不是静默跳过。

### 5. 生成整片字幕（脚本 `gen_film_ass.py`）
```bash
"<你的python.exe>" "<技能>/scripts/gen_film_ass.py" --job . --durations durations2.txt \
    --bounds bounds_cache.json --out all.ass --mode scroll --size 60 --y 900 --t 0
```
时间轴：**页面 i 起始 = Σ_{j<i} (dur_j − T)**，`T` 由 `--t` 指定（默认 0.5）。

⚠️ **`T` 必须和成片模式对齐，否则字幕逐页累积偏移**：

| 成片模式 | 该传的 `--t` | 理由 |
|---|---|---|
| `--mode concat`（硬切，**三段式的默认**） | **`--t 0`** | 拼接不吃重叠，画面第 i 页就在 Σ dur_j 处 |
| `--mode xfade`（交叉淡入） | `--t 0.5`（默认值） | 每级转场吃掉 0.5s 重叠 |

硬切漏传 `--t 0` 的实测后果（3 页样本）：画面在第 11.736s / 22.608s 翻页，字幕却在 11.236s / 21.608s 就位——**每页早 0.5s，50 页到末页早 24.5s，而且不报任何错**。传 `--t 0` 后 ASS 起点与画面边界完全一致（0 / 11.736 / 22.608）。

`--intro 2.5` 用于预挂了 3 秒片头的情况。

### 6. 合成成片（脚本 `gen_final.mjs`）
```bash
node "<技能>/scripts/gen_final.mjs" --job . --mode concat --seg seg --ass all.ass \
    --out 成片.mp4 [--intro intro/intro.mp4 --intro-dur 3.0]
```
然后**用 Bash 工具**执行它写出的 `render_final.sh`。

### 7. 校验 + 交付
```bash
ffprobe -v error -show_entries format=duration,size -of default=nw=1 成片.mp4
ffmpeg -y -ss <中段秒数> -i 成片.mp4 -frames:v 1 -update 1 -q:v 2 _check.png
```
用 Read 工具**看图**确认字幕不溢出、不遮挡。再生成独立字幕：
```bash
node "<技能>/scripts/gen_srt.mjs" --job . --bounds bounds_cache.json --intro 2.5
```
最后：复制成片 + srt 到桌面交付，并 `present_files`。

## 脚本清单

| 脚本 | 语言 | 作用 | 主要参数 |
|---|---|---|---|
| `precheck.mjs` | node | 开工前环境自检（ffmpeg/ffprobe/字体/edge_tts/页图/磁盘预算） | `--job --ff --font --py --minutes` |
| `gen_sentence_ass.py` | py | 配音 + 逐句/滚动字幕（合并旧 3、4 步） | `--in --out --assdir --bounds --mode --voice --rate --size --y --force` |
| `render_all.py` | py | 并行段渲染 + 导出时长表 | `--seg --rows --durations-out --j --no-sub --burn-sub --crf --preset --tail-freeze` |
| `gen_film_ass.py` | py | 整片 ASS（绝对时间轴，支持 scroll/static） | `--durations --bounds --txt-dir --out --mode --size --y --w --h --intro --t` |
| `gen_final.mjs` | node | 合成成片（concat 三段式 / xfade 旧流程） | `--mode --seg --ass --durations --out --master --intro --intro-t --preset --crf --transition` |
| `gen_ass.mjs` | node | 逐页静态 ASS（旧流程兼容） | `--job --outdir --size --font --border --align --mv --mode` |
| `gen_srt.mjs` | node | 独立 SRT（默认逐句级，含片头偏移） | `--durations --bounds --src-dir --out --intro --t --source` |

## 关键参数速查
| 项 | 值 |
|---|---|
| 画幅 | `--w 1920 --h 1080`（横屏）/ `1080 1920`（竖屏） |
| 帧率 | 30 |
| 转场 | xfade fade 0.5s + acrossfade 0.5s（旧 `--mode xfade`）；新架构用硬切 + 字幕时间轴 |
| 字幕（静态逐句） | SimHei 40-46px，白字 + **BorderStyle 3**（`&HCC000000` 半透明黑底），Alignment=2，MarginV=90 |
| 字幕（滚动跑马灯） | SimHei 60px，白字黑描边，`\an7\q2` + `WrapStyle: 2`，`\move(屏宽, Y, -文本宽×1.06, Y, 0, 该页语音毫秒)` |
| 旁白音色 | zh-CN-XiaoxiaoNeural（男声 `zh-CN-YunxiNeural`） |
| 语速折算 | 实测 Xiaoxiao 默认 ≈4.5 字/秒；`--rate +11%` 后 ≈4.8 字/秒 |
| 抽页图 | 本机 ffmpeg **无 PDF 解码器** → LibreOffice + pymupdf |

## 字幕三形态（别搞混）

| 形态 | 关键设置 | 用在哪 |
|---|---|---|
| **静态逐句** | `WrapStyle: 0`，多条 `Dialogue` 按语音边界 | 常规讲解片、信息页 |
| **滚动跑马灯** | `\q2` + `WrapStyle: 2` + `\move` | 要"字幕随语音走完"的演示片 |
| **竖屏补硬字幕** | SimHei 62px、Alignment=2、MarginV≈240 | 1080×1920 分镜自带底部字幕条 |

⚠️ **`\q1` 不是不换行！** `\q1`=行尾换行模式，libass 对无空格中文长句仍按屏宽折行（实测 25 字折成 3 行堆叠）。滚动字幕必须用 `\q2` + 头部 `WrapStyle: 2` **双保险**。静态逐句才用 `WrapStyle: 0`（要自动换行）。

## 本机铁律（本技能反复依赖）
- **Node spawn 外部进程会被沙箱挡**（EBUSY / 无输出）→ 调 ffmpeg、跑 python 一律用 **Bash 工具**。Node 脚本只做「读文件 + 拼命令 + 写文件」。
- ffmpeg / python / ffprobe 在 Bash 里跑正常，长任务配 `dangerouslyDisableSandbox: true`。
- **批量渲染/拼接超过 2 分钟一律挂后台**（`run_in_background`），前台会被 SIGTERM 掐断。
- **Windows 盘符冒号在 ffmpeg filter 里转义无效**：`subtitles='C\:/x/01.ass'` 报 `Unable to parse "original_size"` → 先 `cd` 到目录再用相对名 `subtitles='01.ass'`（`-i` 的图/音仍用绝对路径）。
- **删文件用 Node `fs.unlinkSync`**（`Remove-Item` 不可靠）。
- **Bash 工具偶发 `sandbox-center cmd decisionRecord missing actual resource subject`**：同命令原样重跑通常即恢复；实在不行换 `node.exe <绝对路径脚本>` 这种不带 `VAR=...;` 前缀的写法。

## 踩坑清单（按踩的时间顺序）

1. **多行文案 → ASS 破损**：把 `\n` 直接拼进 Dialogue 行，第二行缺 `Dialogue:` 头，libass 解析失败 → **该页字幕整条消失还报成功**。修：逐行 `esc()` 后用字面的 `\N` 连接。**顺序不能反**——先拼 `\N` 再整体 esc 会变成 `\\N`（字面反斜杠+字母N）。
2. **样式默认值**：`BorderStyle=1`（纯描边）在有底色的 PPT 页上会被吃掉 → 长视频用 **`BorderStyle 3` + `BackColour &HCC000000`**。
3. **`bounds_cache.json` 的键可能是 `"1"` 也可能是 `"01"`**：直接 `cache.get("01")` 会静默取不到，**前 9 页（01~09）整页漏写字幕**。查两种写法。
4. **edge-tts 7.x 事件名是 `SentenceBoundary`，不是 `WordBoundary`**；字段 `{type, offset, duration, text}`，offset/duration 单位是 **100ns**（秒 = ÷10_000_000）。写 `WordBoundary` 永远抓不到，静默 0 条。
5. **`\q1` 不是不换行**（见上）。
6. **本机 ffmpeg 无 PDF 解码器** → 走 LibreOffice + pymupdf。
7. **`zoompan` 会吃掉输入侧 `-t`**：`-loop 1 -t 3.0 -i card.png` 实际只出 2.5s → **`-t` 必须放输出侧**（`-vf` 之后）才能精确 3.0s。
8. **xfade 偏移量必须用 ffprobe 实测段时长算**（`cum - k*T`），否则报「first input is not long enough」；filter_complex 超 1400 字符就写进 `.sh` 再 `bash`，别手拼。
9. **字幕遮挡必须抽帧看**：文字密集页和结尾名片页（自带黑底白字电话条）最容易糊 —— 文字密集页用 `BorderStyle 3` 半透明底解决。
10. **滚动字幕用整页文案**，别只取 `ev[0][0]`（会变成只滚第一句）。
11. **concat `-c copy` 的片头必须带一条实长静音音轨**，且静音轨长度 ≥ 片头时长。踩法：把 `-shortest` 和 3s 片头配一条 2s 静音 → 片头被截成 2s，还不报错。正确姿势：
    ```bash
    ffmpeg -y -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -t 3 -c:a aac silent.m4a   # 先单独做实长静音
    ffmpeg -y -loop 1 -i card.png -i silent.m4a -vf "zoompan=... ,format=yuv420p" \
        -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -r 30 -c:a copy -t 3 intro3.mp4        # 输出侧 -t，别用 -shortest
    ```
12. **concat list 的相对路径以 list 文件所在目录为基准**。把 `file 'bench3/seg/01.mp4'` 写进 `bench3/list.txt` → 解析成 `bench3/bench3/…`，报 `Invalid argument`。**list 一律放工程根目录**，段路径写成 `bench3/seg/01.mp4`。
13. **成品画质瓶颈在「第③步烧字幕」的 CRF，不在段 CRF**。同口径 5 页样本：段 crf18 vs crf23，最终成品体积只差 7.8%（4.71 vs 4.38 MB）——第③步本来就要重编，段里的压缩被抹平了。整片第③步 crf20→crf17 体积 +21%（47.9→58.1 MB），但同帧目视几乎无差。**图文片 778 kbps 够用，别盲目压 crf 追码率数字。**
14. **Node 脚本里 `execSync` 调 ffprobe/ffmpeg 一律 EBUSY**（本机铁律）→ 量测时长体积、抽帧看图，全部走 Bash 工具；Node 只负责读文件、拼命令、写文件。
15. **`--t` 必须和成片模式对齐，否则字幕逐页累积偏移**（本项目最隐蔽的一个）。`gen_film_ass.py` 的时间轴是 `页面 i 起始 = Σ_{j<i}(dur_j − T)`，`T` 默认 **0.5**（为 xfade 转场补偿）。但三段式成片走 `--mode concat` **硬切**，压根没有重叠 → 字幕第 i 页提前 (i−1)×0.5s。实测 3 页：画面在 11.736s / 22.608s 翻页，字幕却在 11.236s / 21.608s 就位；**50 页到末页早 24.5s**，全程零报错。修：硬切成片一律 `--t 0`（改后 ASS 起点 0 / 11.736 / 22.608，与画面边界完全一致）。
16. **`durations.json` 不会自动生成**。`render_all.py` 的 `--rows` 是必需输入，但 7 步管线里没有任何脚本产出它 → 直接跑会报缺文件。用 `ffprobe` 量 `mp3/NN.mp3` 的真实时长自己凑（第 4 步有现成命令）。**别用 bounds 累加代替**：TTS 尾部静音也算在画面时长里。
17. **ASS 时间戳的小数部分是【厘秒】，不是毫秒**（本项目最严重的一个，整条字幕轨错位）。`tss()` 把毫秒余数(0~999)用 `%02d` 打出去，值 ≥100 时会写出 3 位小数：`.100` / `.500` / `.999`。libass 按厘秒解析 → 小数部分**放大 10 倍**：声明 `0:00:00.100` 开始的事件，画面到 **1.0s** 才出现字幕；`.999` 差 9s。误差随每条时间戳的毫秒位跳动（0~9s），**全程零报错**。判定方法：把 ASS 单独渲染到黑底上，用 `setpts=PTS+T/TB` 定位到具体时刻、数一下白像素，声明 `0.100` 却在 1.0s 才出现即中招。修：按厘秒计算并固定输出 2 位 —— `cs = round(s*100)` 后 `"%d:%02d:%02d.%02d"`。
18. **滚动/静态两种模式必须各用一套 ASS 头部**，共用一份会同时踩两个坑：静态字幕不换行（`WrapStyle: 2` 是滚动专用的"不自动换行"）、直接冲出右边界；头部里写死 `PlayResX/PlayResY` 会让 `--w/--h` 形同虚设（竖屏传参无效）。正确姿势：滚动 `WrapStyle 2` + `Alignment 7` + `MarginV y`；静态 `WrapStyle 0` + `Alignment 2` + `MarginV h−y`。

## 写在最后
这套东西的资产是上面 18 条踩坑 + 三段式架构，不是脚本本身。改脚本前先跑 `precheck.mjs`——大部分"跑不动"是环境问题，不是管线问题。

环境安装（ffmpeg / edge-tts / 中文字体）见 `references/setup.md`；版本变更见仓库根目录 `CHANGELOG.md`。
