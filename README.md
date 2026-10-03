<div align="center">

<img src="assets/icon.png" width="110" alt="agent-skills">

# agent-skills

**把 PPT 变成带 AI 旁白和硬字幕的讲解视频 —— 全程本机 ffmpeg 渲染，素材不出本机。**

Turn a PPT/PDF into a page-by-page explainer video with AI narration and burned-in subtitles, rendered fully locally with ffmpeg.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Skills](https://img.shields.io/badge/skills-1-blue.svg)](skills/)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-SKILL.md-7c3aed.svg)](https://code.claude.com/docs/en/skills)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#贡献)

**中文** | [English](#english)

</div>

---

![演示：PPT 逐页讲解视频，带从右向左的滚动字幕](assets/demo.gif)

> ↑ 用本技能自己生成的 3 页样例（原速截取 8 秒）：页图 + AI 旁白 + 滚动跑马灯字幕。
> 换成你自己 PPT 的成片片段会更有说服力——录制方式见下方「演示素材」。

## 这是什么

一个自研 **Agent Skills** 合集。每个技能都是一个独立目录：一份写给 Agent 看的 `SKILL.md`（含触发词、管线步骤、参数速查、踩坑清单）+ 一组可复用的 `scripts/`。

技能不是"提示词模板"，而是**把一条真实工作流固化成可执行的管线**——包含实测数据、失败模式和修复方法，让 Agent 第一次就按对的方式做。

## 技能清单

| 技能 | 一句话 | 版本 | 状态 |
|---|---|---|---|
| [`ppt-to-explainer-video-ffmpeg`](skills/ppt-to-explainer-video-ffmpeg/) | 用本机 ffmpeg 把 PPT/PDF 转成带 AI 旁白 + 硬字幕的逐页讲解视频 | v1.1.0 | 稳定 |

<!-- 新增技能时，在 skills/ 下建目录并在此表加一行；CI 会自动校验 frontmatter。 -->

---

## 旗舰技能：`ppt-to-explainer-video-ffmpeg`

### 它解决什么问题

你有一份 PPT/PDF，需要一段"有人在讲"的视频：**每页停留、配中文旁白、字幕压在画面上**。

常见做法是把素材传到在线服务，或者剪映里手工对轴。这个技能走另一条路：

- **纯本机渲染**：ffmpeg 在本机跑，素材不上传，内网也能用（只有 TTS 合成那一步需要联网）。
- **旁白与字幕天然同步**：一次 TTS 流里同时拿到音频和 `SentenceBoundary` 语音边界，不用事后强制对齐。
- **改字幕不用重配音**：拼接产物是一份无字幕母版，换字幕形态/加片头只重烧一遍。

触发方式就是自然语言：「把这份 PPT 做成讲解视频」「给课件配个口播」「配字幕的逐页视频」。

### 三段式架构（v1.1.0 重构）

旧做法是「每段各烧各的字幕 → 套 N-1 级 xfade 拼接」。50 页实测 **65s + 63s = 128s**，而且每加一级 xfade 都要重编一遍全片，像素一代代掉质量。

新做法把**字幕烧录**和**转场拼接**解耦：

```
① 段渲染(不带字幕, 并行 j=4)  →  seg/NN.mp4 + durations2.txt
② -f concat -c copy 硬切      →  master.mp4（0 重编码，无字幕母版）
③ 单遍烧 all.ass              →  成片.mp4（唯一一次全片重编码）
```

### 实测性能（50 页 / 1920×1080 / 30fps）

| 环节 | v1.0.0 | v1.1.0 |
|---|---|---|
| 段渲染 | 65 s（串行、段内烧字幕） | **41.7 s**（并行 `--j 4`） |
| 转场拼接 | 63 s（49 级 xfade，每级重编全片） | **1.4 s**（硬切，0 重编码） |
| 烧字幕 | 含在段渲染里 | 全片只 1 遍：47.5 s / 34.8 s（veryfast） |
| **合计** | **128 s** | **90.6 s（-29%）**，veryfast 档 **77.9 s（-39%）** |

整片回归：体积 **119.5 MB → 47.9 MB**（旧版的 40%），码率 2059 → 778 kbps，抽帧目测文字清晰度不变。

> 并行是最大单项收益：同样不烧字幕，`--j 1` 58.8 s vs `--j 4` 41.7 s（**-29%**）。

### 三种字幕形态

| 形态 | 关键设置 | 用在哪 |
|---|---|---|
| **静态逐句** | `WrapStyle: 0`，多条 `Dialogue` 按语音边界切 | 常规讲解片、信息页 |
| **滚动跑马灯** | `\q2` + `WrapStyle: 2` + `\move`，与语音逐句同步 | 要"字幕随语音走完"的演示片 |
| **竖屏补硬字幕** | SimHei 62px、Alignment=2、MarginV≈240 | 1080×1920 分镜自带底部字幕条 |

⚠️ `\q1` **不是**不换行——libass 对无空格中文长句仍会按屏宽折行。滚动字幕必须 `\q2` + 头部 `WrapStyle: 2` **双保险**。

### 快速开始

**1. 安装技能**（把技能目录放进你的 Agent 运行时的 skills 目录）

```bash
# GitHub
git clone https://github.com/__GH_USER__/agent-skills.git
# Gitee 镜像（国内访问更快，内容一致）
git clone https://gitee.com/__GITEE_USER__/agent-skills.git

# Claude Code（用户级）
mkdir -p ~/.claude/skills
cp -r agent-skills/skills/ppt-to-explainer-video-ffmpeg ~/.claude/skills/

# Cursor
cp -r agent-skills/skills/ppt-to-explainer-video-ffmpeg ~/.cursor/skills/

# 其他支持 Agent Skills 的运行时：把该技能目录整体复制到它的 skills 目录即可
```

**2. 装依赖并自检**

```bash
# ffmpeg + Python 3.10+ + edge-tts + 一款中文字体
pip install edge_tts

node "<技能目录>/scripts/precheck.mjs" --job "<JOBDIR>" --minutes 4
```

`precheck.mjs` 会一次性告诉你缺哪一项，并自动挑出真正装了 `edge_tts` 的那个 Python 解释器（多解释器是高频坑）。

**3. 跑管线**（每步都能单独重跑）

```bash
# ① 页图 01.png…NN.png → JOBDIR，每页旁白写进 vo3/NN.txt
# ② 配音 + 逐句字幕（一次 TTS 流同时产出 mp3 和语音边界）
python "<技能>/scripts/gen_sentence_ass.py" --job . --in vo3 --out mp3 \
    --assdir ass --bounds bounds_cache.json --mode scroll --size 60 --y 900

# ③ 逐页时长表（render_all.py 的必需输入，不会自动生成）
python -c "import json,glob,os,subprocess as sp;rows=[{'page':int(os.path.basename(p)[:2]),'dur':round(float(sp.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',p],capture_output=True,text=True).stdout.strip()),3)} for p in sorted(glob.glob('mp3/*.mp3'))];json.dump(rows,open('durations.json','w'),ensure_ascii=False,indent=1)"

# ④ 并行段渲染（不带字幕）
python "<技能>/scripts/render_all.py" --job . --seg seg --rows durations.json \
    --durations-out durations2.txt --no-sub --j 4 --crf 23 --preset veryfast --tail-freeze 3.0

# ⑤ 整片绝对时间轴字幕（硬切成片必须 --t 0，否则字幕逐页累积提前）
python "<技能>/scripts/gen_film_ass.py" --job . --durations durations2.txt \
    --bounds bounds_cache.json --out all.ass --mode scroll --size 60 --y 900 --t 0

# ⑥ 合成成片
node "<技能>/scripts/gen_final.mjs" --job . --mode concat --seg seg --ass all.ass --out 成片.mp4

# ⑦ 独立 SRT（逐句级，带 UTF-8 BOM）
node "<技能>/scripts/gen_srt.mjs" --job . --bounds bounds_cache.json --intro 2.5
```

详细参数、时间轴公式、字体/画幅设置见 [`SKILL.md`](skills/ppt-to-explainer-video-ffmpeg/SKILL.md)。

### 演示素材

README 顶部那个 GIF 是这么截的（同样可以用来录你自己 PPT 的演示）：

```bash
# 从成片里截 8 秒，压成 150 KB 上下、适合放进 README 的 GIF
ffmpeg -y -ss 10.5 -t 8 -i 成片.mp4 \
  -vf "fps=12,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  -loop 0 assets/demo.gif
```

挑片段的原则：**要包含一次翻页，且字幕正在滚动**——一眼就能看出这是「逐页讲解 + 字幕跟语音走」，而不是一张静态截图。

### 环境要求

| 依赖 | 说明 |
|---|---|
| **ffmpeg + ffprobe** | 必须。自动探测 PATH / 常见安装目录，也可 `--ff` 显式指定 |
| **Python 3.10+** | 必须。需 `pip install edge_tts`（微软 Azure 免费神经语音，免 key） |
| **中文字体** | Windows 自带 SimHei；Linux 建议 `fonts-noto-cjk`；macOS 用 PingFang |
| **网络** | 仅 TTS 合成那一步需要联网，素材本身不上传 |

安装细节与各平台命令见 [`references/setup.md`](skills/ppt-to-explainer-video-ffmpeg/references/setup.md)。

### 这个技能的"资产"其实是踩坑清单

脚本本身不难写，难的是那些**不报错但结果错**的坑。SKILL.md 里固化了 18 条实测踩坑，例如：

- **ASS 时间戳把毫秒写进了厘秒字段**：小数部分被 libass 放大 10 倍，声明 0.1s 开始的事件到 1.0s 才出现字幕，`0~9s` 误差随条目跳动且零报错。这条是本仓库做端到端验证时抓到并修掉的。
- **字幕逐页累积偏移**：硬切成片漏传 `--t 0`，字幕每页早 0.5s —— 3 页早 1.0s、**50 页到末页早 24.5s**，全程零报错。
- **前 9 页整页漏写字幕**：语音边界缓存的键名可能是 `"1"` 也可能是 `"01"`，`cache.get("01")` 静默取空。
- **多行文案导致整页字幕消失还报成功**：ASS 必须**先转义再拼 `\N`**；顺序反了会变成字面反斜杠+字母 N。
- **edge-tts 7.x 事件名是 `SentenceBoundary` 不是 `WordBoundary`**，写错永远抓不到、静默 0 条。
- **`zoompan` 会吃掉输入侧 `-t`**：`-t` 必须放**输出侧**才能精确 3.0s 片头。
- **concat `-c copy` 的片头必须带实长静音音轨**，否则片头被截短还不报错。
- **concat list 的相对路径以 list 文件所在目录为基准**，放错目录就 `Invalid argument`。

全部 18 条 + 每条的现象/原因/修法见 [`SKILL.md`](skills/ppt-to-explainer-video-ffmpeg/SKILL.md#踩坑清单按踩的时间顺序)。

### 已知边界

- 语音合成需联网（edge-tts）；素材本身不上传。
- 不保留原 PPT 动画（每页抽静态页图）。
- 扫描件/纯图 PPT 需先做 OCR 取文本。
- 目前解说词为中文优化（音色、字数折算按中文实测）。

---

## 仓库结构

```
agent-skills/
├── skills/
│   └── ppt-to-explainer-video-ffmpeg/
│       ├── SKILL.md          # 技能主体：触发条件、管线、参数、踩坑
│       ├── references/
│       │   └── setup.md      # 各平台环境安装
│       └── scripts/          # 7 个参数化脚本（node + python）
├── tools/
│   ├── validate-skills.mjs   # 校验所有 SKILL.md frontmatter
│   └── pack_skill.py         # 打包上架 ZIP（含泄露检查）
├── assets/icon.png
├── CHANGELOG.md
└── LICENSE
```

## 贡献

欢迎 Issue / PR。提交前请确保本地通过：

```bash
node tools/validate-skills.mjs
python tools/pack_skill.py --skill ppt-to-explainer-video-ffmpeg --out dist --leak-check
```

新增技能请放在 `skills/<技能名>/`，`SKILL.md` 的 frontmatter `name` 必须与目录名一致——CI 会校验。

## 许可

[MIT](LICENSE) © 2026 zhangjw

---

## English

### What is this

A collection of handcrafted **Agent Skills**. Each skill is a self-contained directory: a `SKILL.md` written for the agent (trigger phrases, pipeline steps, parameter reference, pitfall list) plus reusable `scripts/`.

These are not prompt templates. Each one freezes a **real, measured workflow** into an executable pipeline — including benchmark numbers, failure modes, and their fixes — so the agent gets it right the first time.

### `ppt-to-explainer-video-ffmpeg`

Turns a PPT/PDF into a page-by-page explainer video: slide image + Chinese AI narration + burned-in subtitles + transitions. **Rendered entirely by local ffmpeg** — your material never leaves your machine (only the TTS step needs network).

**Architecture (v1.1.0)** — subtitles and transitions are decoupled:

```
① render segments in parallel, no subtitles  →  seg/NN.mp4 + durations2.txt
② concat with -c copy (no re-encode)         →  master.mp4  (subtitle-free master)
③ burn all.ass once                          →  final.mp4   (only full re-encode)
```

**Measured on a 50-page deck @ 1920×1080/30fps:**

| Stage | v1.0.0 | v1.1.0 |
|---|---|---|
| Segment render | 65 s (serial, subtitles baked in) | **41.7 s** (parallel `--j 4`) |
| Transition concat | 63 s (49-level xfade, re-encodes the whole film each level) | **1.4 s** (hard cut, zero re-encode) |
| Subtitle burn | inside segment render | one pass over the film |
| **Total** | **128 s** | **90.6 s (-29%)**, 77.9 s with `-preset veryfast` (**-39%**) |

Output size dropped from 119.5 MB to 47.9 MB. Because `master.mp4` has no subtitles, you can switch subtitle style or add an intro **without re-synthesizing narration or re-rendering segments**.

**Requirements:** ffmpeg + ffprobe, Python 3.10+ with `pip install edge_tts`, and a CJK font (SimHei on Windows, Noto CJK on Linux, PingFang on macOS). Run `scripts/precheck.mjs` first — it reports exactly what is missing.

**Install:** copy `skills/ppt-to-explainer-video-ffmpeg/` into your agent runtime's skills directory (e.g. `~/.claude/skills/`).

The real value of this skill is its **18 documented pitfalls** — bugs that produce wrong output *without* raising an error (ASS timestamps inflated 10× by writing milliseconds into the centisecond field, cumulative subtitle drift from a mismatched `--t`, subtitle-key mismatches, ASS escaping order, `zoompan` swallowing `-t`, silent audio in concat, …). See [`SKILL.md`](skills/ppt-to-explainer-video-ffmpeg/SKILL.md).

### License

[MIT](LICENSE) © 2026 zhangjw
