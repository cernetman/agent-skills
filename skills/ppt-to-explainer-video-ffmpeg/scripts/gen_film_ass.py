#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate the film-wide ASS (all.ass) — the subtitle file used for the "single-pass subtitle burn" of the three-stage architecture.

Why this exists:
  The old architecture was "burn each segment's subtitles separately, then stitch with N-1 levels of xfade", which cost 49 full-film re-encodes
  (63s measured for 50 pages) and lost quality as the pixels were re-encoded generation after generation.
  The new architecture is "segments are rendered without subtitles -> hard-cut concat with -c copy -> burn subtitles in one pass with this single all.ass",
  with transitions folded into the subtitle timeline (a 0.5s gap between pages is enough; the visual transition is concat's hard cut).
  To keep cross-fades instead: see gen_final.mjs --mode xfade (legacy pipeline).

Timeline algorithm (equivalent to xfade compensation):
  start of page i (1-based) = Σ_{j<i} (dur_j - T)

Usage:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=".")
    ap.add_argument("--durations", default="durations2.txt")
    ap.add_argument("--bounds", default="bounds_cache.json")
    ap.add_argument("--txt-dir", default="vo3", help="per-page script directory (fallback used by static mode)")
    ap.add_argument("--out", default="all.ass")
    ap.add_argument("--mode", choices=["static", "scroll"], default="scroll")
    ap.add_argument("--size", type=int, default=60)
    ap.add_argument("--y", type=int, default=900)
    ap.add_argument("--w", type=int, default=1920)   # pass 1080 for portrait
    ap.add_argument("--h", type=int, default=1080)   # pass 1920 for portrait
    ap.add_argument("--intro", type=float, default=0.0, help="film start offset (use 2.5 if an intro was prepended)")
    ap.add_argument("--t", type=float, default=0.5,
                    help="transition duration compensation; a hard-cut (concat) film must pass 0, only xfade mode uses 0.5 (the default)")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    durs_path = os.path.join(job, a.durations)
    if not os.path.exists(durs_path):
        raise SystemExit(
            "[ERROR] %s not found. render_all.py writes it (--durations-out); "
            "run that step before this one." % durs_path)
    durs = {}
    for line in open(durs_path, encoding="utf-8"):
        line = line.strip()
        if line:
            k, v = line.split("=")
            durs[int(k.strip())] = float(v)
    if not durs:
        raise SystemExit("[ERROR] no durations at all inside %s, run render_all.py first" % a.durations)
    maxi = max(durs)

    bounds_path = os.path.join(job, a.bounds)
    try:
        # utf-8-sig: tolerates JSON written with a BOM by Notepad / PowerShell
        bounds = json.load(open(bounds_path, encoding="utf-8-sig"))
    except FileNotFoundError:
        bounds = {}
    except ValueError as e:
        raise SystemExit("[ERROR] %s is not valid JSON: %s" % (bounds_path, e))

    # The two modes need different headers; sharing one produces two different kinds of accident (measured):
    #   scroll: one event for the whole page + \move, needs both \q2 and WrapStyle 2 to be safe, style aligned top-left, and y is its vertical coordinate.
    #   static: many events, one per sentence, needs WrapStyle 0 to wrap automatically; bottom center (Alignment 2, MarginV measured from the bottom).
    #   With WrapStyle 2 hard-coded, long static sentences never wrap and run straight off the right edge.
    # This also makes --w/--h actually take effect (HEAD used to hard-code 1920x1080, so portrait arguments did nothing).
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
        # bounds_cache.json keys may be "1" or "01" (written by different callers, see gen_sentence_ass.cache_get).
        # Looking up str(i) only would silently miss them -> the first 9 pages lose their subtitles; in static mode the whole film gets 0 events.
        ev = bounds.get(str(i)) or bounds.get("%02d" % i) or bounds.get(i) or []
        if a.mode == "scroll":
            txt = ev[0][0] if ev else open(os.path.join(job, a.txt_dir, "%02d.txt" % i),
                                          encoding="utf-8").read().strip()
            # Text width is measured for real with PIL; the end point is -W*1.06 so the whole sentence scrolls past the left edge
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
            "[ERROR] not a single subtitle event was generated (mode=%s); refusing to write an empty subtitle file.\n"
            "  bounds_cache.json keys = %s\n"
            "  static mode depends entirely on this cache; an empty one usually means the cache keys do not match the page numbers, or that the cache was never generated.\n"
            "  Re-run gen_sentence_ass.py to produce the mp3 files + bounds_cache.json, then run this script."
            % (a.mode, keys if keys else "(empty / file missing)"))

    out = os.path.join(job, a.out)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    warn = ""
    if a.t:
        warn = ("\n  [!] --t %.1f assumes xfade transition compensation; if the final film is assembled with --mode concat (hard cut),\n"
                "      every page's subtitles will start %.1fs too early and the error accumulates page by page — pass --t 0 for a hard-cut film" % (a.t, a.t))
    print("wrote %s, %d events, timeline covers 0 ~ %.3fs%s"
          % (out, len(lines) - 1, film_end, warn))


if __name__ == "__main__":
    main()
