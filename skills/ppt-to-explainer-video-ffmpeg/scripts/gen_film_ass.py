#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成整片 ASS(all.ass)——三段式架构里"单遍烧字幕"用的那份字幕。

为什么要有这个:
  旧架构是"每段各烧各的字幕,再套 N-1 级 xfade 拼接",代价是 49 次全片重编码(50 页实测 63s)
  且像素一代代重编码会掉质量。
  新架构是"段落不烧字幕 -> -c copy 硬切拼接 -> 用这一份 all.ass 单遍烧字幕",
  转场融进字幕时间轴(页与页之间留 0.5s 空档即可,画面转场用 concat 的硬切)。
  想保留交叉淡入:见 gen_final.mjs --mode xfade(兼容旧流程)。

时间轴算法(与 xfade 补偿等价):
  页面 i(从 1 开始)起始 = Σ_{j<i} (dur_j - T)

用法:
  python gen_film_ass.py --job . --durations durations2.txt --bounds bounds_cache.json \
      --out all.ass --mode scroll --size 60 --y 900 --intro 2.5
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

def _first(cands, fallback):
    for c in cands:
        if os.path.exists(c):
            return c
    return fallback


FONT = _first(["C:/Windows/Fonts/simhei.ttf",
               "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
               "/System/Library/Fonts/PingFang.ttc",
               "/usr/share/fonts/wqy-zenhei.ttc"], "C:/Windows/Fonts/simhei.ttf")
HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,SimHei,{size},&H00FFFFFF,&H000000FF,&H00000000,&HCC000000,1,0,0,0,100,100,0,0,3,3,0,7,60,60,{y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def tss(s):
    ms = max(0, int(round(s * 1000)))
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    sec, cs = divmod(r, 1000)
    return "%d:%02d:%02d.%02d" % (h, m, sec, cs)


def esc(s):
    return s.replace("\\", "\\\\").replace(",", "\\,").replace("{", "\\{").replace("}", "\\}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=".")
    ap.add_argument("--durations", default="durations2.txt")
    ap.add_argument("--bounds", default="bounds_cache.json")
    ap.add_argument("--txt-dir", default="vo3", help="逐页文案目录(static 模式兜底用)")
    ap.add_argument("--out", default="all.ass")
    ap.add_argument("--mode", choices=["static", "scroll"], default="scroll")
    ap.add_argument("--size", type=int, default=60)
    ap.add_argument("--y", type=int, default=900)
    ap.add_argument("--w", type=int, default=1920)   # 竖屏传 1080
    ap.add_argument("--h", type=int, default=1080)   # 竖屏传 1920
    ap.add_argument("--intro", type=float, default=0.0, help="整片起点偏移(预挂了片头就填 2.5)")
    ap.add_argument("--t", type=float, default=0.5,
                    help="转场时长补偿;硬切(concat)成片必须传 0,只有 xfade 模式才用 0.5(默认)")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    durs = {}
    for line in open(os.path.join(job, a.durations), encoding="utf-8"):
        line = line.strip()
        if line:
            k, v = line.split("=")
            durs[int(k.strip())] = float(v)
    if not durs:
        raise SystemExit("[错误] %s 里没有任何时长,先跑 render_all.py" % a.durations)
    maxi = max(durs)

    try:
        bounds = json.load(open(os.path.join(job, a.bounds), encoding="utf-8"))
    except FileNotFoundError:
        bounds = {}

    lines = [HEAD.format(size=a.size, y=a.y)]
    base = 0.0
    film_end = 0.0
    for i in range(1, maxi + 1):
        page_start = base + a.intro
        page_dur = durs.get(i, 0.0)
        film_end = max(film_end, page_start + page_dur)
        ev = bounds.get(str(i)) or bounds.get(i) or []
        if a.mode == "scroll":
            txt = ev[0][0] if ev else open(os.path.join(job, a.txt_dir, "%02d.txt" % i),
                                          encoding="utf-8").read().strip()
            # 文本宽用 PIL 实测,终点取 -W*1.06 保证整句滚出左缘
            try:
                from PIL import ImageFont
                tw = ImageFont.truetype(FONT, a.size).getlength(txt)
            except Exception:
                tw = len(txt) * a.size
            x1, x2 = a.w, -int(tw * 1.06) - 40
            n = max(int(page_dur * 1000), 100)
            head = "{\\an7\\q2\\move(%d,%d,%d,%d,0,%d)}" % (x1, a.y, x2, a.y, n)
            lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s%s"
                         % (tss(page_start), tss(page_start + page_dur), head, esc(txt)))
        else:
            for txt, off, dur in ev:
                s0 = page_start + off / 1e7
                s1 = s0 + dur / 1e7
                if s1 <= s0:
                    continue
                lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s"
                             % (tss(s0), tss(s1 + 0.25), esc(txt)))
        if i < maxi:
            base += durs[i] - a.t

    out = os.path.join(job, a.out)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    warn = ""
    if a.t:
        warn = ("\n  [!] --t %.1f 是按 xfade 转场补偿算的;若成片走 --mode concat(硬切),\n"
                "      字幕会每页提前 %.1fs 且逐页累积 —— 硬切成片请传 --t 0" % (a.t, a.t))
    print("写出 %s, %d 条事件, 时间轴覆盖 0 ~ %.3fs%s"
          % (out, len(lines) - 1, film_end, warn))


if __name__ == "__main__":
    main()
