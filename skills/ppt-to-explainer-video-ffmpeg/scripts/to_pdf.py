#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[New in v2.0.0] Convert PPT / PPTX / DOC / DOCX / ODP into a single PDF — step 0 of the video pipeline.

Why this step has to exist (fixes "the picture drifts", 2026-10-07):
  The old flow fed the PPT straight into page extraction and relied on libraries such as python-pptx to
  **re-lay out the pages from the object model**.
  python-pptx only reads shape coordinates: no font substitution, no automatic line wrapping, no line-height
  correction — so the moment a text box is smaller than its text, a font is missing, or a master placeholder is
  not rendered, the resulting image no longer matches what PowerPoint shows. It shows up as **a drifting picture,
  text on top of images, elements out of place**.
  After converting to PDF the layout is frozen in one pass by LibreOffice's full layout engine (a PDF records
  absolute coordinates), and extraction afterwards is nothing but "rasterize every PDF page" — **no re-layout at
  all**, so the drift disappears at the root.

Usage:
  python to_pdf.py --input "<file.pptx>" --job <JOBDIR> [--out source.pdf]
  python to_pdf.py --input "<file.pdf>"  --job <JOBDIR>     # already a PDF -> register it directly, instant

Behaviour:
  - Input is already a PDF -> idempotent passthrough (copy/register to pdf/source.pdf), LibreOffice is not touched.
  - The output PDF lands in <JOBDIR>/pdf/source.pdf as a **retainable intermediate artifact**, and
    pdf_to_pages.py reads it from there. It is kept by default (so you can re-run and verify the page count);
    delete it explicitly with --clean.
  - LibreOffice's user profile goes to a temporary directory and is removed when the conversion ends, whether it
    succeeded or not — it is bulky, and keeping it would pollute the job directory. The converted artifact itself
    is never deleted.

Failure handling (always a **plain error plus an actionable next step** — never a silent skip, never a half-written artifact):
  1) soffice not found       -> report every path probed, plus how to install it or point at it (--soffice)
  2) soffice exits non-zero  -> print the last 600 characters of stderr, plus the three usual fixes
  3) soffice exits 0 but produced no PDF -> say outright that "the conversion did not succeed" and name the prime
     suspects (protected / encrypted / corrupt)
  4) timeout                 -> kill the process group and report it, suggesting a larger --timeout
  5) 0 pages produced        -> error out (an empty PDF silently yields a 0-segment video downstream)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# LibreOffice-supported input extensions -> description (only ever shown to a human inside an error message)
KNOWN = {
    ".pptx": "PowerPoint 2007+", ".ppt": "PowerPoint 97-2003",
    ".docx": "Word 2007+", ".doc": "Word 97-2003",
    ".odp": "OpenDocument Presentation", ".ods": "OpenDocument Spreadsheet",
    ".rtf": "RTF", ".xlsx": "Excel 2007+", ".xls": "Excel 97-2003",
    ".pdf": "PDF (passthrough, no conversion)",
}
PDF_EXT = ".pdf"


def die(msg, code=1):
    print("[ERROR] " + msg, file=sys.stderr)
    sys.exit(code)


def find_soffice(explicit=""):
    """Locate soffice via PATH -> common install directories; no machine-specific path is hard-coded.

    On Windows prefer soffice.com: soffice.exe is the GUI launcher and **returns immediately** without waiting for
    the conversion to finish, which looks like "exit 0 but the file is not there yet". soffice.com is the console
    build and blocks until the work is really done. We have been bitten by this pitfall — do not change it back.
    """
    if explicit:
        if os.path.exists(explicit):
            return explicit
        die("--soffice path does not exist: %s" % explicit)

    env = os.environ.get("SOFFICE_PATH", "").strip()
    cands = []
    if env:
        cands.append(env)
    for name in ("soffice.com", "soffice.exe", "soffice", "libreoffice"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    cands += [
        "C:/Program Files/LibreOffice/program/soffice.com",
        "C:/Program Files/LibreOffice/program/soffice.exe",
        "C:/Program Files (x86)/LibreOffice/program/soffice.com",
        "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
        "/usr/bin/soffice", "/usr/local/bin/soffice", "/snap/bin/libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return ""


def page_count(pdf):
    """Count pages. Prefer pymupdf, otherwise fall back to counting /Type /Page with a regex. Returns 0 if both fail (the caller treats that as unknown)."""
    try:
        import pymupdf
        with pymupdf.open(pdf) as d:
            return d.page_count
    except Exception:
        pass
    try:
        with open(pdf, "rb") as f:
            blob = f.read()
        n = len(re.findall(rb"/Type\s*/Page[^s]", blob))
        m = re.findall(rb"/Count\s+(\d+)", blob)
        if m:
            return max(n, int(max(m, key=lambda x: int(x))))
        return n
    except Exception:
        return 0


def file_stable(p, quiet_ms=1200, timeout=30):
    """Wait until the file size has stayed unchanged for quiet_ms -> consider it written out (soffice flushes asynchronously)."""
    t0 = time.time()
    last, last_t = -1, time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(p):
            sz = os.path.getsize(p)
            if sz > 0 and sz == last:
                if (time.time() - last_t) * 1000 >= quiet_ms:
                    return True
            else:
                last, last_t = sz, time.time()
        time.sleep(0.3)
    return os.path.exists(p) and os.path.getsize(p) > 0


def convert(src, out_pdf, soffice, timeout, profile):
    """Run one headless conversion. Returns (ok, detailed reason). Never raises; the reason is reported by the caller."""
    outdir = os.path.dirname(out_pdf)
    os.makedirs(outdir, exist_ok=True)
    # Separate profile: avoid fighting the user's own running LibreOffice over the same configuration (it would refuse to convert)
    purl = "file:///" + profile.replace("\\", "/").lstrip("/")
    cmd = [
        soffice,
        "-env:UserInstallation=%s" % purl,
        "--headless", "--norestore", "--invisible", "--nolockcheck", "--nodefault",
        "--convert-to", "pdf:impress_pdf_Export",
        "--outdir", outdir, src,
    ]
    flags = {}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, **flags)
    except subprocess.TimeoutExpired:
        return False, "soffice conversion timed out (>%ss). A large or image-heavy deck can take several minutes " \
                      "to convert; raise the limit with --timeout 600." % timeout
    except Exception as e:  # failed to launch, and so on
        return False, "Failed to launch soffice: %r" % (e,)

    produced = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + PDF_EXT)
    if cp.returncode != 0:
        return False, "soffice exited with code %d\n%s" % (
            cp.returncode, ((cp.stderr or cp.stdout or "").strip()[-600:] or "(no output)"))
    if not os.path.exists(produced) or os.path.getsize(produced) == 0:
        # exit 0 with no file: this is what soffice does with encrypted/protected/corrupt documents
        return False, ("soffice exited 0 but produced no PDF. Common causes: "
                       "(1) the document is encrypted, read-only or protected (2) the document is corrupt "
                       "(3) the file is locked exclusively by WPS/Office "
                       "— save a copy manually from Office/WPS first, or close whatever is holding the file open and retry.")
    if not file_stable(produced):
        return False, "The PDF never settled on disk (size was still changing after 30s); the disk may be slow or the conversion was interrupted."
    if os.path.abspath(produced) != os.path.abspath(out_pdf):
        if os.path.exists(out_pdf):
            os.remove(out_pdf)
        shutil.move(produced, out_pdf)
    return True, ""


def main():
    ap = argparse.ArgumentParser(description="PPT/document -> PDF (pipeline step added in v2.0.0)")
    ap.add_argument("--input", required=True, help="source file (.pptx/.ppt/.docx/.pdf ...)")
    ap.add_argument("--job", default=".", help="job directory; pdf/ is created inside it")
    ap.add_argument("--out", default=os.path.join("pdf", "source.pdf"),
                    help="output path (relative to --job), default pdf/source.pdf — aligned with the pdf_to_pages.py default")
    ap.add_argument("--soffice", default="", help="explicit soffice path (for when detection fails)")
    ap.add_argument("--timeout", type=int, default=300, help="conversion timeout in seconds, default 300")
    ap.add_argument("--clean", action="store_true",
                    help="delete the pdf/ directory after converting and extracting pages (intermediate artifacts are kept by default)")
    ap.add_argument("--force", action="store_true", help="re-convert even when a PDF already exists")
    a = ap.parse_args()

    src = os.path.abspath(a.input)
    if not os.path.exists(src):
        die("Input file not found: %s" % src)
    job = os.path.abspath(a.job)
    os.makedirs(job, exist_ok=True)
    out_pdf = os.path.join(job, a.out)
    ext = os.path.splitext(src)[1].lower()
    t0 = time.time()

    # --- idempotent: already a PDF, so register it and never touch LibreOffice ---
    if ext == PDF_EXT:
        if os.path.abspath(src) != os.path.abspath(out_pdf):
            os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
            if os.path.exists(out_pdf) and not a.force:
                pass
            else:
                shutil.copyfile(src, out_pdf)
        n = page_count(out_pdf)
        print("[PASSTHROUGH] input is already a PDF, skipping conversion -> %s (%s pages)" % (out_pdf, n if n else "?"))
        _write_meta(job, out_pdf, src, "passthrough", n, time.time() - t0)
        if a.clean:
            _rm(out_pdf)
        print("Next: python pdf_to_pages.py --job <JOBDIR> --pdf %s --outdir pages" % a.out)
        return

    if ext not in KNOWN:
        print("[NOTICE] %s is not one of the common office extensions (%s); trying anyway, and any failure will be reported."
              % (ext, ", ".join(sorted(KNOWN))), file=sys.stderr)

    # --- an artifact already exists and is not older than the source -> skip (editing the PPT makes its mtime newer, so it re-converts automatically) ---
    if os.path.exists(out_pdf) and not a.force:
        if os.path.getmtime(out_pdf) >= os.path.getmtime(src):
            n = page_count(out_pdf)
            print("[SKIP] %s is already up to date (not older than the source file). Add --force to re-convert" % a.out)
            _write_meta(job, out_pdf, src, "cached", n, 0.0)
            if a.clean:
                _rm(out_pdf)
            return

    soffice = find_soffice(a.soffice)
    if not soffice:
        die("Cannot find LibreOffice (soffice), so %s cannot be converted to PDF.\n"
            "  Install LibreOffice: https://www.libreoffice.org/download/\n"
            "  Or save it manually as PDF from Office/WPS and then run:\n"
            "    python pdf_to_pages.py --input \"<manually exported.pdf>\" --outdir pages\n"
            "  If you really would rather not install it, point at it explicitly with --soffice \"<full soffice path>\" (already probed: %s)"
            % (ext, ", ".join(["PATH", "C:/Program Files/LibreOffice/program", "/usr/bin",
                               "/Applications/LibreOffice.app"])))

    tmpdir = tempfile.mkdtemp(prefix="_lo_profile_")
    try:
        ok, why = convert(src, out_pdf, soffice, a.timeout, tmpdir)
    finally:
        # the profile directory is always removed: it is bulky and unrelated to the result; keeping it only pollutes the job directory
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not ok:
        die("PPT -> PDF conversion failed.\nReason: %s\n"
            "  This step is the foundation of the whole pipeline (the layout is frozen here); **no PDF, no video** — "
            "do not skip it." % why)

    n = page_count(out_pdf)
    if n == 0:
        # better to fail loudly than to let a 0-page PDF flow downstream: it would silently produce an empty 0-segment video
        _rm(out_pdf)
        die("The converted PDF reports no page count (probably 0 pages / encrypted / corrupt), so the artifact has been deleted. "
            "Save a PDF manually from Office/WPS and run pdf_to_pages.py on that one instead.")

    sz = os.path.getsize(out_pdf) / 1048576.0
    _write_meta(job, out_pdf, src, "libreoffice", n, time.time() - t0)
    print("[DONE] %s -> %s (%d pages, %.1f MB, %.1fs)" % (ext, out_pdf, n, sz, time.time() - t0))
    if a.clean:
        _rm(out_pdf)
        print("[CLEAN] removed the intermediate PDF as requested by --clean")
    else:
        print("[KEPT] intermediate artifact %s (keep it to re-run or verify the page count; delete it with --clean once you are happy)" % a.out)
    print("Next: python pdf_to_pages.py --job <JOBDIR> --pdf %s --outdir pages" % a.out)


def _rm(p):
    try:
        os.remove(p)
    except OSError as e:
        print("[WARNING] cannot delete %s: %s" % (p, e), file=sys.stderr)


def _write_meta(job, out_pdf, src, how, pages, secs):
    """Keep a provenance record: when the finished video has a problem you must be able to trace which file and which page each page image came from."""
    m = {
        "source_file": src,
        "source_ext": os.path.splitext(src)[1].lower(),
        "pdf": out_pdf,
        "converter": how,
        "pages": pages,
        "elapsed_sec": round(secs, 2),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "skill_version": "2.0.0",
    }
    p = os.path.join(job, "pdf", "source.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
