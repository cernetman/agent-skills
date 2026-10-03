#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 skills/<name>/ 打成可上架的 ZIP（SKILL.md 必须位于压缩包第一层）。

用法:
    python tools/pack_skill.py --skill ppt-to-explainer-video-ffmpeg --out dist
    python tools/pack_skill.py --skill ppt-to-explainer-video-ffmpeg --out dist --leak-check

退出码: 0 成功 / 1 参数或校验失败 / 2 泄露检查未通过
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "dist"}
SKIP_SUFFIX = (".pyc", ".zip", ".mp4", ".m4a", ".mp3")

# 打包前要挡住的泄露特征
LEAK_PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]", re.I), "Windows 用户绝对路径"),
    (re.compile(r"[A-Za-z]:[\\/]{1,2}(?:my files|Users|Documents|Desktop)[\\/]", re.I), "本机绝对路径"),
    (re.compile(r"/(?:home|Users)/[^/\s\"']+/"), "Unix 用户绝对路径"),
    (re.compile(r"(?:api[_-]?key|secret|passwd|password|access[_-]?token)\s*[=:]\s*\S+", re.I), "疑似密钥赋值"),
]


def collect(src: Path, name: str) -> list[tuple[Path, str]]:
    """按 (磁盘路径, 压缩包内路径) 收集文件，SKILL.md 排在最前。"""
    files: list[tuple[Path, str]] = []
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(names):
            if f.endswith(SKIP_SUFFIX) or f in {".DS_Store", "Thumbs.db", "desktop.ini"}:
                continue
            full = Path(root) / f
            rel = full.relative_to(src).as_posix()
            files.append((full, f"{name}/{rel}"))
    files.sort(key=lambda item: (item[1].count("/"), item[1]))
    return files


def leak_scan(files: list[tuple[Path, str]], username: str) -> list[str]:
    hits: list[str] = []
    for full, arc in files:
        for pat, label in LEAK_PATTERNS:
            if pat.search(arc):
                hits.append(f"{arc}: 条目名命中{label}")
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if username and username.lower() in text.lower():
            hits.append(f"{arc}: 正文出现本机用户名 {username!r}")
        for pat, label in LEAK_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{arc}: {label} -> {m.group(0)[:60]!r}")
    return hits


def read_version(skill_md: Path) -> str:
    m = re.search(r"^version:\s*(\S+)\s*$", skill_md.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def main() -> int:
    ap = argparse.ArgumentParser(description="打包 skills/<name> 为上架 ZIP")
    ap.add_argument("--skill", required=True, help="skills/ 下的技能目录名")
    ap.add_argument("--out", default="dist", help="输出目录，相对路径按仓库根算（默认 dist）")
    ap.add_argument("--repo", default=str(REPO_ROOT), help="仓库根目录")
    ap.add_argument("--version", help="覆盖文件名版本号（默认读 SKILL.md 的 version）")
    ap.add_argument("--leak-check", action="store_true", help="打包前扫描用户名/绝对路径/疑似密钥")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    src = repo / "skills" / args.skill
    skill_md = src / "SKILL.md"
    if not skill_md.is_file():
        print(f"[x] 找不到 {skill_md}", file=sys.stderr)
        return 1

    files = collect(src, args.skill)
    if not files:
        print(f"[x] {src} 下没有可打包的文件", file=sys.stderr)
        return 1

    if args.leak_check:
        hits = leak_scan(files, getpass.getuser())
        if hits:
            print("[x] 泄露检查未通过，已中止打包：", file=sys.stderr)
            for h in hits:
                print("   -", h, file=sys.stderr)
            return 2
        print(f"[√] 泄露检查通过（{len(files)} 个文件）")

    version = args.version or read_version(skill_md)
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_zip = out_dir / f"{args.skill}-{version}.zip"

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for full, arc in files:
            z.write(full, arc)
            print(f"  + {arc}")

    with zipfile.ZipFile(out_zip) as z:
        names = z.namelist()
        broken = z.testzip()
        first = names[0]

    print(f"\n打包文件数 = {len(names)}")
    print(f"namelist 首项 = {first}")
    print(f"完整性 = {'OK' if broken is None else 'BAD: ' + str(broken)}")
    print(f"ZIP 大小 = {out_zip.stat().st_size / 1024:.1f} KB")

    if first != f"{args.skill}/SKILL.md" or broken is not None:
        print("[x] 校验失败：SKILL.md 不在压缩包第一层，或 ZIP 损坏", file=sys.stderr)
        return 1
    print(f"输出 = {out_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
