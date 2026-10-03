#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package skills/<name>/ into a publishable ZIP (SKILL.md must be at the archive root).

Usage:
    python tools/pack_skill.py --skill ppt-to-explainer-video-ffmpeg --out dist
    python tools/pack_skill.py --skill ppt-to-explainer-video-ffmpeg --out dist --leak-check

Exit codes: 0 success / 1 bad arguments or validation failure / 2 leak check failed
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

# Leak patterns to block before packaging
LEAK_PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]", re.I), "Windows user absolute path"),
    (re.compile(r"[A-Za-z]:[\\/]{1,2}(?:my files|Users|Documents|Desktop)[\\/]", re.I), "local machine absolute path"),
    (re.compile(r"/(?:home|Users)/[^/\s\"']+/"), "Unix user absolute path"),
    (re.compile(r"(?:api[_-]?key|secret|passwd|password|access[_-]?token)\s*[=:]\s*\S+", re.I), "suspected secret assignment"),
]


def collect(src: Path, name: str) -> list[tuple[Path, str]]:
    """Collect files as (disk path, in-archive path), with SKILL.md first."""
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
                hits.append(f"{arc}: entry name matches {label}")
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Match the username on alphanumeric boundaries only. A plain substring
        # test fires on any word that merely contains it (e.g. the maintainer's
        # own handle inside "cernetman"), while this still catches the real
        # cases: C:\Users\cerne\, /home/cerne/, cerne@host, user=cerne.
        if username and re.search(
            r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(username), text, re.I
        ):
            hits.append(f"{arc}: content contains the local username {username!r}")
        for pat, label in LEAK_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{arc}: {label} -> {m.group(0)[:60]!r}")
    return hits


def read_version(skill_md: Path) -> str:
    m = re.search(r"^version:\s*(\S+)\s*$", skill_md.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def main() -> int:
    ap = argparse.ArgumentParser(description="Package skills/<name> into a publishable ZIP")
    ap.add_argument("--skill", required=True, help="name of the skill directory under skills/")
    ap.add_argument("--out", default="dist", help="output directory; relative paths are resolved against the repo root (default: dist)")
    ap.add_argument("--repo", default=str(REPO_ROOT), help="repository root directory")
    ap.add_argument("--version", help="override the version in the file name (default: read version from SKILL.md)")
    ap.add_argument("--leak-check", action="store_true", help="scan for usernames / absolute paths / suspected secrets before packaging")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    src = repo / "skills" / args.skill
    skill_md = src / "SKILL.md"
    if not skill_md.is_file():
        print(f"[x] {skill_md} not found", file=sys.stderr)
        return 1

    files = collect(src, args.skill)
    if not files:
        print(f"[x] no files to package under {src}", file=sys.stderr)
        return 1

    if args.leak_check:
        hits = leak_scan(files, getpass.getuser())
        if hits:
            print("[x] leak check failed, packaging aborted:", file=sys.stderr)
            for h in hits:
                print("   -", h, file=sys.stderr)
            return 2
        print(f"[√] leak check passed ({len(files)} files)")

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

    print(f"\nfiles packaged = {len(names)}")
    print(f"first namelist entry = {first}")
    print(f"integrity = {'OK' if broken is None else 'BAD: ' + str(broken)}")
    print(f"ZIP size = {out_zip.stat().st_size / 1024:.1f} KB")

    if first != f"{args.skill}/SKILL.md" or broken is not None:
        print("[x] validation failed: SKILL.md is not at the archive root, or the ZIP is corrupt", file=sys.stderr)
        return 1
    print(f"output = {out_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
