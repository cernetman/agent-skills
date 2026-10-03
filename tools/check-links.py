#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check every markdown file in this repository.

Two things go wrong silently in a docs repository and look bad the moment
someone clicks them, so CI checks both on every push and pull request:

  1. a relative link or image points at a file that does not exist
  2. a "#anchor" does not resolve to a heading in the target file
     (resolved with GitHub's slug rules: lowercase, punctuation dropped,
     spaces turned into hyphens)

It also validates every skill's SKILL.md frontmatter against the Agent Skills
specification: `name` must match its directory and use only lowercase letters,
digits and hyphens; `description` must be present and at most 1024 characters.

Usage:
    python tools/check-links.py            # checks the whole repository
Exit codes: 0 clean / 1 problems found
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.M)
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.S)
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_NAME = 64
MAX_DESCRIPTION = 1024

SKIP_DIRS = {".git", "dist", "node_modules", "__pycache__", ".venv"}


def slug(text: str) -> str:
    """Approximate the anchor GitHub generates for a heading."""
    text = text.strip().lower()
    text = re.sub(r"[`*_\[\]()#!]", "", text)  # drop inline markup
    text = "".join(c for c in text if unicodedata.category(c)[0] != "P" or c == "-")
    return text.replace(" ", "-")


def markdown_files() -> list[Path]:
    out = []
    for p in REPO_ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.relative_to(REPO_ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


def main() -> int:
    problems: list[str] = []

    files = markdown_files()
    headings = {
        p: {slug(m.group(2)) for m in HEADING_RE.finditer(p.read_text(encoding="utf-8"))}
        for p in files
    }

    checked = 0
    for md, anchors in headings.items():
        for m in LINK_RE.finditer(md.read_text(encoding="utf-8")):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#!")):
                continue
            checked += 1
            rel = md.relative_to(REPO_ROOT)
            path_part, _, anchor = target.partition("#")
            resolved = (md.parent / path_part).resolve() if path_part else md
            if path_part and not resolved.exists():
                problems.append(f"{rel}: broken link -> {target}")
                continue
            if anchor and resolved in headings and anchor not in headings[resolved]:
                problems.append(
                    f"{rel}: anchor '#{anchor}' not found in "
                    f"{resolved.relative_to(REPO_ROOT)}"
                )

    # --- skill frontmatter -------------------------------------------------
    skills = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir()) if SKILLS_DIR.is_dir() else []
    for skill in skills:
        skill_md = skill / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"skills/{skill.name}: no SKILL.md")
            continue
        fm = FRONTMATTER_RE.match(skill_md.read_text(encoding="utf-8"))
        if not fm:
            problems.append(f"skills/{skill.name}/SKILL.md: no frontmatter block")
            continue
        fields = dict(re.findall(r"^([A-Za-z0-9_-]+):\s*(.*)$", fm.group(1), re.M))
        name = fields.get("name", "")
        desc = fields.get("description", "")
        if name != skill.name:
            problems.append(f"skills/{skill.name}/SKILL.md: name is '{name}'")
        if not NAME_RE.fullmatch(name):
            problems.append(f"skills/{skill.name}/SKILL.md: name breaks the [a-z0-9-] rule")
        if len(name) > MAX_NAME:
            problems.append(f"skills/{skill.name}/SKILL.md: name is {len(name)} chars (max {MAX_NAME})")
        if not desc:
            problems.append(f"skills/{skill.name}/SKILL.md: description missing")
        elif len(desc) > MAX_DESCRIPTION:
            problems.append(
                f"skills/{skill.name}/SKILL.md: description is {len(desc)} chars "
                f"(max {MAX_DESCRIPTION})"
            )
        print(
            f"  skill {name}: name {len(name)} chars, description {len(desc)} chars, "
            f"license {fields.get('license', '(none)')}"
        )

    print(f"\n  markdown files: {len(files)}   relative links checked: {checked}")
    if problems:
        print(f"\n[x] {len(problems)} problem(s):")
        for p in problems:
            print("   -", p)
        return 1
    print("\n[ok] links, anchors and skill frontmatter are all valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
