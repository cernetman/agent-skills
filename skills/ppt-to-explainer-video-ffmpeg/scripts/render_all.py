#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""并行分段渲染:NN.png + NN.mp3 -> NN.mp4(默认不烧字幕),并导出 durations2.txt

性能要点(2026-10-02 实测):
  - 默认 --no-sub 渲染段落(不带字幕),配合"硬切 concat + 单遍烧字幕"的三段式,
    可整片去掉 N-1 级 xfade 重编码(50 页实测省掉 49 次全片重编)。
  - --j N 用线程池并行跑 ffmpeg:8 核测试机实测 4 路 ≈ 串行 3 倍提速。

用法:
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
    """返回第一个存在的路径;都不在就退回 PATH 上的 ffmpeg。"""
    import shutil
    for c in cands:
        if c == "ffmpeg" and shutil.which(c):
            return c
        if os.path.exists(c):
            return c
    return "ffmpeg"


FF = _which(["ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg",
             "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
             os.path.expanduser("~/bin/ffmpeg.exe")])  # 可用 --ff 覆盖


def build_cmd(ff, png, mp3, out, dur, burn, ass_rel, crf, preset):
    vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1")
    if burn and ass_rel:
        # 盘符冒号在 filter 里转义无效 -> 用相对名(需先 cd 到字幕目录)
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
    ap.add_argument("--burn-sub", action="store_true", help="在段内烧字幕(旧架构,慢且损失质量)")
    ap.add_argument("--ass-dir", default="ass", help="--burn-sub 时用的字幕目录")
    ap.add_argument("--crf", default="23")
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--j", type=int, default=4, help="并行路数,1=串行")
    ap.add_argument("--tail-freeze", type=float, default=0.0,
                    help="最后一页额外定格秒数")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    segd = os.path.join(job, a.seg)
    os.makedirs(segd, exist_ok=True)

    rows_path = os.path.join(job, a.rows)
    if not os.path.exists(rows_path):
        raise SystemExit(
            "[缺文件] %s\n"
            "  这是 render_all.py 的必需输入,不会自动生成。它是逐页时长表,格式:\n"
            "      [{\"page\": 1, \"dur\": 11.736}, {\"page\": 2, \"dur\": 10.872}]\n"
            "  dur 用 ffprobe 量 mp3/NN.mp3 的真实时长(别用 bounds 累加,TTS 尾部静音也占画面时长):\n"
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
                raise SystemExit("[缺文件] %s —— 先跑抽页图与配音" % p)
        dur = round(float(r["dur"]) + (a.tail_freeze if r["page"] == total else 0.0), 3)
        cmd = build_cmd(a.ff, png, mp3, out, dur, a.burn_sub,
                        (tag + ".ass") if a.burn_sub else None,
                        a.crf, a.preset)
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if cp.returncode != 0:
            raise SystemExit("[渲染失败] %s\n%s" % (tag, cp.stderr[-600:]))
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

    print("渲染完成 %d 段, 耗时 %.1fs (并行 j=%d, 平均 %.2fs/段)"
          % (len(done), el, a.j, el / max(len(done), 1)))


if __name__ == "__main__":
    main()
