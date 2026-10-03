#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配音 + 逐句/滚动字幕一次性生成(合并旧流程第 3、4 步)。

为什么合并成一步:
  旧流程是"先跑一遍 edge-tts 出 mp3,再跑一遍拿边界",要调两次 TTS。
  这里一次流里既写 mp3 又收集 SentenceBoundary 边界,天然一致;
  并把边界落成 bounds_cache.json,后面改字幕版(静态/滚动)不用重新配音。

⚠️ 关键事实(踩过):
  - edge-tts 7.x 的事件名是 **SentenceBoundary**,不是 WordBoundary。
    写 `chunk["type"] == "WordBoundary"` 永远匹配不到,会静默得到 0 条边界。
  - offset / duration 单位是 100ns,秒 = ÷10_000_000。
  - 首句 offset 通常从 1_000_000(0.1s)开始,所以逐句起点统一减 0.1s 更贴合听感。

用法:
  python gen_sentence_ass.py --job . --in vo3 --out mp3 --bounds bounds_cache.json \
      --voice zh-CN-XiaoxiaoNeural --rate +11% --mode scroll --size 60
"""
import argparse
import asyncio
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
Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&HCC000000,1,0,0,0,100,100,0,0,3,3,0,7,60,60,{y},1

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


def cache_get(cache, tag):
    """bounds_cache.json 的键可能是 "1" 也可能是 "01"(不同写法喂进来的)。
    直接 cache.get("01") 会静默取不到 -> 前 9 页(01~09)整页漏写字幕。
    两种写法都探一次。"""
    if not cache:
        return []
    v = cache.get(tag)
    if v is None:
        v = cache.get(str(int(tag)))
    return v or []


def text_width(txt, size):
    """文本像素宽(滚动字幕算滚动时长要用)"""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(FONT, size).getlength(txt)
    except Exception:
        return len(txt) * size  # 退化估算:中文字宽≈字号


async def synth_page(text, voice, rate, mp3_path, tag):
    import edge_tts
    bounds = []
    comm = edge_tts.Communicate(text, voice, rate=rate)
    os.makedirs(os.path.dirname(mp3_path) or ".", exist_ok=True)
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                # 7.x 是 SentenceBoundary;写成 WordBoundary 会静默 0 条
                bounds.append([chunk["text"], chunk["offset"], chunk["duration"]])
    if not bounds:
        print("[警告] %s 没拿到 SentenceBoundary,该页只会生成整页一条字幕" % tag)
    return bounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=".")
    ap.add_argument("--in", dest="indir", default="vo3", help="逐页文案目录 NN.txt")
    ap.add_argument("--out", dest="outdir", default="mp3")
    ap.add_argument("--assdir", default="ass")
    ap.add_argument("--bounds", default="bounds_cache.json")
    ap.add_argument("--mode", choices=["static", "scroll"], default="static")
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    ap.add_argument("--rate", default="+11%")
    ap.add_argument("--size", type=int, default=60)
    ap.add_argument("--y", type=int, default=900)
    ap.add_argument("--w", type=int, default=1920)
    ap.add_argument("--h", type=int, default=1080)
    ap.add_argument("--force", action="store_true", help="已有 mp3 也重新配音")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    ind, outd, assd = (os.path.join(job, a.indir), os.path.join(job, a.outdir),
                       os.path.join(job, a.assdir))
    os.makedirs(outd, exist_ok=True)
    os.makedirs(assd, exist_ok=True)

    pages = sorted(f for f in os.listdir(ind) if f.endswith(".txt"))
    if not pages:
        raise SystemExit("[错误] %s 里没找到 NN.txt,先写好逐页旁白" % ind)

    cache = {}
    if os.path.exists(os.path.join(job, a.bounds)):
        try:
            cache = json.load(open(os.path.join(job, a.bounds), encoding="utf-8"))
        except Exception:
            cache = {}

    n_syn = 0
    for f in pages:
        tag = f[:-4]
        txt = open(os.path.join(ind, f), encoding="utf-8").read().strip()
        mp3p = os.path.join(outd, tag + ".mp3")
        if os.path.exists(mp3p) and not a.force:
            continue
        if not txt:
            continue
        cache[tag] = asyncio.run(synth_page(txt, a.voice, a.rate, mp3p, tag))
        n_syn += 1
        print("[配音] %s ok 句数=%d" % (tag, len(cache[tag])), flush=True)

    json.dump(cache, open(os.path.join(job, a.bounds), "w", encoding="utf-8"),
              ensure_ascii=False)

    # 生成逐页 ass(static:逐句;scroll:整页一条 + \move)
    ws = 2 if a.mode == "scroll" else 0
    n_ass = 0
    for f in pages:
        tag = f[:-4]
        ev = cache_get(cache, tag)
        if not ev:
            continue
        head = HEAD.format(w=a.w, h=a.h, ws=ws, font="SimHei", size=a.size, y=a.y)
        if a.mode == "scroll":
            # 滚动字幕要整页文案一起滚(旧版就是这么出的片);
            # 只取 ev[0][0] 会变成只滚第一句 —— 实测踩过。
            body = open(os.path.join(ind, tag + ".txt"), encoding="utf-8").read().strip()
            if not body and ev:
                body = "".join(x[0] for x in ev)
            mv = "{\\an7\\q2\\move(%d,%d,-%d,%d,0,9000)}" % (
                a.w, a.y, int(text_width(body, a.size) * 1.06) + 40, a.y)
            lines = ["Dialogue: 0,0:00:00.00,9:59:59.99,Default,,0,0,0,,%s%s"
                     % (mv, esc(body))]
        else:
            lines = []
            for txt, off, dur in ev:
                s0 = off / 1e7 - 0.1
                s1 = (off + dur) / 1e7 + 0.25
                if s1 <= s0:
                    continue
                lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s"
                             % (tss(s0), tss(s1), esc(txt)))
        if not lines:
            continue
        open(os.path.join(assd, tag + ".ass"), "w", encoding="utf-8").write(head + "\n".join(lines) + "\n")
        n_ass += 1

    print("新配音 %d 页 / 写出 %d 页 ass (mode=%s, size=%d, 缓存=%s)"
          % (n_syn, n_ass, a.mode, a.size, a.bounds))


if __name__ == "__main__":
    main()
