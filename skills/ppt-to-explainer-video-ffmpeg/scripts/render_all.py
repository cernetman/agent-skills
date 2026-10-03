#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Parallel segment rendering: NN.png + NN.mp3 -> NN.mp4 (no burned-in subtitles by default), plus export of durations2.txt

Performance notes (measured 2026-10-02):
  - render segments with --no-sub by default (no subtitles); combined with the three-stage "hard-cut concat + single-pass subtitle burn",
    this removes the N-1 levels of xfade re-encoding for the whole film (measured: 49 full-film re-encodes saved on a 50-page deck).
  - --j N runs ffmpeg in parallel through a thread pool: on an 8-core test machine, 4 workers measured ≈3x the serial speed.

Usage:
  python render_all.py --job <JOBDIR> --seg seg --rows durations.json \
      --durations-out durations2.txt --no-sub --j 4
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")

def _which(cands):
    """Return the first path that exists; if none do, fall back to ffmpeg on PATH."""
    import shutil
    for c in cands:
        if c == "ffmpeg" and shutil.which(c):
            return c
        if os.path.exists(c):
            return c
    return "ffmpeg"


FF = _which(["ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg",
             "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
             os.path.expanduser("~/bin/ffmpeg.exe")])  # can be overridden with --ff


def build_cmd(ff, png, mp3, out, dur, burn, ass_rel, crf, preset):
    vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1")
    if burn and ass_rel:
        # A drive-letter colon cannot be escaped inside a filter -> use a relative name (cd into the subtitle directory first)
        vf += ",subtitles='%s'" % ass_rel
    cmd = [ff, "-y", "-loop", "1", "-i", png, "-i", mp3, "-vf", vf, "-t", "%.3f" % dur,
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
    if burn:
        cmd += ["-shortest"]
    cmd.append(out)
    return cmd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=".")
    ap.add_argument("--seg", default="seg")
    ap.add_argument("--rows", default="durations.json")
    ap.add_argument("--durations-out", default="durations2.txt")
    ap.add_argument("--ff", default=FF)
    ap.add_argument("--no-sub", action="store_true", default=True)
    ap.add_argument("--burn-sub", action="store_true", help="burn subtitles inside the segment (old architecture, slow and lossy)")
    ap.add_argument("--ass-dir", default="ass", help="subtitle directory used with --burn-sub")
    ap.add_argument("--crf", default="23")
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--j", type=int, default=4, help="number of parallel workers, 1=serial")
    ap.add_argument("--tail-freeze", type=float, default=0.0,
                    help="extra freeze seconds on the last page")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    segd = os.path.join(job, a.seg)
    os.makedirs(segd, exist_ok=True)

    rows_path = os.path.join(job, a.rows)
    if not os.path.exists(rows_path):
        raise SystemExit(
            "[MISSING FILE] %s\n"
            "  This is a required input for render_all.py and is never generated automatically. It is the per-page duration table, formatted as:\n"
            "      [{\"page\": 1, \"dur\": 11.736}, {\"page\": 2, \"dur\": 10.872}]\n"
            "  Measure dur with ffprobe on the real length of mp3/NN.mp3 (don't accumulate the bounds; trailing TTS silence also occupies screen time):\n"
            "      ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 mp3/01.mp3\n"
            % rows_path)
    rows = json.load(open(rows_path, encoding="utf-8"))
    rows.sort(key=lambda r: r["page"])
    total = len(rows)

    def one(r):
        tag = "%02d" % r["page"]
        png = os.path.join(job, "pages", tag + ".png")
        mp3 = os.path.join(job, "mp3", tag + ".mp3")
        out = os.path.join(segd, tag + ".mp4")
        for p in (png, mp3):
            if not os.path.exists(p):
                raise SystemExit("[MISSING FILE] %s — extract page images and synthesize the narration first" % p)
        dur = round(float(r["dur"]) + (a.tail_freeze if r["page"] == total else 0.0), 3)
        cmd = build_cmd(a.ff, png, mp3, out, dur, a.burn_sub,
                        (tag + ".ass") if a.burn_sub else None,
                        a.crf, a.preset)
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if cp.returncode != 0:
            raise SystemExit("[RENDER FAILED] %s\n%s" % (tag, cp.stderr[-600:]))
        return tag, dur

    t0 = time.time()
    done = []
    if a.j > 1:
        with ThreadPoolExecutor(max_workers=a.j) as ex:
            for tag, dur in ex.map(one, rows):
                done.append((tag, dur))
                print("[%d/%d] %s dur=%.2fs" % (len(done), total, tag, dur), flush=True)
    else:
        for r in rows:
            tag, dur = one(r)
            done.append((tag, dur))
            print("[%d/%d] %s dur=%.2fs" % (len(done), total, tag, dur), flush=True)
    el = time.time() - t0

    with open(os.path.join(job, a.durations_out), "w", encoding="utf-8") as f:
        for tag, dur in done:
            f.write("%s=%.3f\n" % (tag, dur))

    print("rendering done: %d segments, %.1fs elapsed (parallel j=%d, average %.2fs/segment)"
          % (len(done), el, a.j, el / max(len(done), 1)))


if __name__ == "__main__":
    main()
