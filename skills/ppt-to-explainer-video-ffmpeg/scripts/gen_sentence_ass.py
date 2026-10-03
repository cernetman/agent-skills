#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Narration + sentence-level/scrolling subtitles generated in one go (merges steps 3 and 4 of the old pipeline).

Why merge them into one step:
  The old pipeline ran edge-tts once to produce mp3 files, then ran it again just to get the boundaries: two TTS passes.
  Here a single stream both writes the mp3 and collects the SentenceBoundary events, so the two are consistent by construction;
  the boundaries are also saved to bounds_cache.json, so switching subtitle versions (static/scrolling) later needs no re-synthesis.

⚠️ Key facts (learned the hard way):
  - In edge-tts 7.x the event name is **SentenceBoundary**, not WordBoundary.
    Writing `chunk["type"] == "WordBoundary"` never matches anything and silently yields 0 boundaries.
  - offset / duration are in 100ns units, so seconds = ÷10_000_000.
  - The first sentence's offset usually starts at 1_000_000 (0.1s), so subtracting 0.1s from every sentence start lines up better with what you hear.

Usage:
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
    """seconds -> ASS timestamp "H:MM:SS.cc".

    ⚠️ The fractional part of an ASS timestamp is [centiseconds] (always 2 digits), not milliseconds. If you print the millisecond remainder
    (0~999) directly with %02d, any value >= 100 writes 3 digits (e.g. .100); libass parses it as centiseconds -> the whole fractional part is
    scaled 10x (0.1s is read as 1.0s, 0.999s as 9.99s), the entire subtitle track drifts and nothing is reported.
    Measured: an event declared to start at 0:00:00.100 only shows its subtitle on screen at 1.0s.
    """
    cs = max(0, int(round(s * 100)))
    h, r = divmod(cs, 360000)
    m, r = divmod(r, 6000)
    sec, c = divmod(r, 100)
    return "%d:%02d:%02d.%02d" % (h, m, sec, c)


def esc(s):
    """Escape ASS text; newlines must [be escaped line by line first, then joined with a literal \\N].

    The order cannot be reversed: joining \\N first and then escaping the whole thing turns it into a literal backslash + the letter N.
    Splicing a bare newline straight into the Dialogue line leaves the second line without its "Dialogue:" header -> libass fails to parse it,
    **the entire subtitle disappears and no error is raised** (see SKILL.md pitfall 1).
    """
    return "\\N".join(
        ln.replace("\\", "\\\\").replace(",", "\\,").replace("{", "\\{").replace("}", "\\}")
        for ln in s.splitlines()
    )


def cache_get(cache, tag):
    """bounds_cache.json keys may be "1" or "01" (written by different callers).
    A plain cache.get("01") silently misses them -> pages 01~09 lose their subtitles entirely.
    Probe both spellings."""
    if not cache:
        return []
    v = cache.get(tag)
    if v is None:
        v = cache.get(str(int(tag)))
    return v or []


def text_width(txt, size):
    """Text width in pixels (needed to compute the scrolling subtitle's duration)"""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(FONT, size).getlength(txt)
    except Exception:
        return len(txt) * size  # fallback estimate: CJK glyph width ≈ font size


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
                # 7.x emits SentenceBoundary; writing WordBoundary silently gives 0 events
                bounds.append([chunk["text"], chunk["offset"], chunk["duration"]])
    if not bounds:
        print("[WARNING] got no SentenceBoundary for %s; this page will only get one full-page subtitle" % tag)
    return bounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=".")
    ap.add_argument("--in", dest="indir", default="vo3", help="per-page script directory (NN.txt)")
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
    ap.add_argument("--force", action="store_true", help="re-synthesize even if the mp3 already exists")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    ind, outd, assd = (os.path.join(job, a.indir), os.path.join(job, a.outdir),
                       os.path.join(job, a.assdir))
    os.makedirs(outd, exist_ok=True)
    os.makedirs(assd, exist_ok=True)

    pages = sorted(f for f in os.listdir(ind) if f.endswith(".txt"))
    if not pages:
        raise SystemExit("[ERROR] no NN.txt found in %s, write the per-page narration first" % ind)

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
        print("[TTS] %s ok sentences=%d" % (tag, len(cache[tag])), flush=True)

    json.dump(cache, open(os.path.join(job, a.bounds), "w", encoding="utf-8"),
              ensure_ascii=False)

    # Generate the per-page ass (static: sentence by sentence; scroll: one event for the page + \move)
    ws = 2 if a.mode == "scroll" else 0
    n_ass = 0
    for f in pages:
        tag = f[:-4]
        ev = cache_get(cache, tag)
        if not ev:
            continue
        head = HEAD.format(w=a.w, h=a.h, ws=ws, font="SimHei", size=a.size, y=a.y)
        if a.mode == "scroll":
            # Scrolling subtitles must scroll the whole page's script together (that is how the old version produced films);
            # taking only ev[0][0] scrolls just the first sentence — measured the hard way.
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

    print("newly synthesized %d pages / wrote ass for %d pages (mode=%s, size=%d, cache=%s)"
          % (n_syn, n_ass, a.mode, a.size, a.bounds))


if __name__ == "__main__":
    main()
