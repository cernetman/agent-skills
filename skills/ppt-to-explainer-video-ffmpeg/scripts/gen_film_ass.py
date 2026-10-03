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
PlayResX: {w}
PlayResY: {h}
WrapStyle: {ws}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&HCC000000,1,0,0,0,100,100,0,0,3,3,0,{align},60,60,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def tss(s):
    """秒 -> ASS 时间戳 "H:MM:SS.cc"。

    ⚠️ ASS 的小数部分是【厘秒】(固定 2 位),不是毫秒。若把毫秒余数(0~999)直接用 %02d 打出去,
    值 >= 100 时会写出 3 位(如 .100),libass 按厘秒解析 -> 整个小数部分放大 10 倍
    (0.1s 被读成 1.0s,0.999s 被读成 9.99s),字幕整轨错位且不报错。
    实测:声明 0:00:00.100 开始的事件,画面到 1.0s 才出现字幕。
    """
    cs = max(0, int(round(s * 100)))
    h, r = divmod(cs, 360000)
    m, r = divmod(r, 6000)
    sec, c = divmod(r, 100)
    return "%d:%02d:%02d.%02d" % (h, m, sec, c)


def esc(s):
    """转义 ASS 文本;换行必须【先按行 esc,再用字面的 \\N 连接】。

    顺序不能反:先拼 \\N 再整体 esc 会变成字面反斜杠 + 字母 N。
    直接把裸换行拼进 Dialogue 行,第二行会缺 "Dialogue:" 头 -> libass 解析失败,
    **整条字幕消失而且不报错**(见 SKILL.md 踩坑 1)。
    """
    return "\\N".join(
        ln.replace("\\", "\\\\").replace(",", "\\,").replace("{", "\\{").replace("}", "\\}")
        for ln in s.splitlines()
    )


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

    bounds_path = os.path.join(job, a.bounds)
    try:
        # utf-8-sig:容忍被记事本 / PowerShell 写入 BOM 的 json
        bounds = json.load(open(bounds_path, encoding="utf-8-sig"))
    except FileNotFoundError:
        bounds = {}
    except ValueError as e:
        raise SystemExit("[错误] %s 不是合法 JSON:%s" % (bounds_path, e))

    # 两种模式必须用不同的头部,共用一份会出两种事故(实测):
    #   滚动:整页一条 + \move,要 \q2 + WrapStyle 2 双保险,样式左上对齐,y 就是它的纵坐标。
    #   静态:逐句多条,要 WrapStyle 0 才会自动换行;底部居中(Alignment 2,MarginV 从底部量)。
    #   写死 WrapStyle 2 时,静态长句不换行、直接冲出右边界。
    # 同时把 --w/--h 真正用上(之前 HEAD 写死 1920x1080,竖屏传参不生效)。
    if a.mode == "scroll":
        ws, align, mv = 2, 7, a.y
    else:
        ws, align, mv = 0, 2, max(0, a.h - a.y)

    lines = [HEAD.format(w=a.w, h=a.h, ws=ws, align=align, font="SimHei",
                         size=a.size, mv=mv)]
    base = 0.0
    film_end = 0.0
    for i in range(1, maxi + 1):
        page_start = base + a.intro
        page_dur = durs.get(i, 0.0)
        film_end = max(film_end, page_start + page_dur)
        # bounds_cache.json 的键可能是 "1" 也可能是 "01"(不同写法喂进来的,见 gen_sentence_ass.cache_get)。
        # 只查 str(i) 会静默取不到 -> 前 9 页漏字幕;静态模式更是整片 0 条事件。
        ev = bounds.get(str(i)) or bounds.get("%02d" % i) or bounds.get(i) or []
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

    if len(lines) == 1:
        keys = sorted(bounds.keys())[:8] if bounds else []
        raise SystemExit(
            "[错误] 一条字幕事件都没生成 (mode=%s),拒绝写出空字幕文件。\n"
            "  bounds_cache.json 的键 = %s\n"
            "  静态模式完全依赖这份缓存;为空通常是缓存键与页码对不上,或缓存没生成。\n"
            "  先重跑 gen_sentence_ass.py 产出 mp3 + bounds_cache.json,再跑本脚本。"
            % (a.mode, keys if keys else "（空/文件不存在）"))

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
