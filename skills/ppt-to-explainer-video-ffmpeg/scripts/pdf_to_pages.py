#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v2.0.0 PDF -> pages/NN.png + source.txt — step 1 of the video pipeline (replaces the old doc-to-pages.mjs).

Why this script exists (2026-10-07):
  Step 1 of the old SKILL.md said "reuse doc-to-pages.mjs from the ppt-explain skill", but that skill
  **was not installed at all**, so every run needed a hand-rolled fallback, and the fallbacks all differed ->
  the extracted page images came out at inconsistent sizes and aspect ratios, downstream render_all.py scales
  and pads everything to 1920x1080, and the picture drifted along with them.
  This step is now pinned down as a script inside this repository: **the only input is a PDF**, and the page
  image aspect ratio is decided by the PDF alone.

The output contract is exactly the same as the old step (downstream render_all.py / gen_sentence_ass.py need not change a single line):
  <outdir>/01.png ... NN.png     the extracted page images
  source.txt                     per-page text, to look at while writing the narration

Usage:
  python pdf_to_pages.py --job <JOBDIR> [--pdf pdf/source.pdf] [--input x.pdf] [--outdir pages]
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_PDF = os.path.join("pdf", "source.pdf")


def die(msg, code=1):
    print("[ERROR] " + msg, file=sys.stderr)
    sys.exit(code)


def resolve_pdf(job, a):
    """Prefer --pdf, then --input, finally falling back to <job>/pdf/source.pdf.

    --input may point straight at a PDF: a PDF exported by hand from Office/WPS can enter the pipeline in one
    step, with no need to copy it into pdf/ first.
    """
    if a.input:
        p = os.path.abspath(a.input)
        if not os.path.exists(p):
            die("Input PDF not found: %s" % p)
        return p
    p = os.path.join(job, a.pdf)
    if not os.path.exists(p):
        # Spell out what the previous step should have been
        die("Cannot find %s — convert the source file to PDF first (step 0, added in v2.0.0):\n"
            "    python to_pdf.py --input \"<your.pptx>\" --job .\n"
            "  If it is already a PDF, just pass --input \"<that.pdf>\"." % a.pdf)
    return p


def main():
    ap = argparse.ArgumentParser(description="PDF -> per-page PNG + text (v2.0.0)")
    ap.add_argument("--job", default=".")
    ap.add_argument("--pdf", default=DEFAULT_PDF, help="PDF path relative to --job")
    ap.add_argument("--input", default="", help="give the PDF path directly, absolute or relative (takes priority over --pdf)")
    ap.add_argument("--outdir", default="pages", help="page image output directory, relative to --job")
    ap.add_argument("--dpi", type=int, default=144,
                    help="rasterization resolution. 144dpi is about 1920x1080 for a 16:9 content area, so the default is enough; pass 288 for 4K")
    ap.add_argument("--scale-to", default="",
                    help="force the long edge in pixels (e.g. 1920). When given, it scales by that and ignores dpi")
    ap.add_argument("--min-dpi", type=int, default=0,
                    help="floor resolution: for PDFs whose pages are themselves small, so you do not extract tiny images that downstream blows up into mush")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    pdf = resolve_pdf(job, a)
    outdir = os.path.join(job, a.outdir)
    os.makedirs(outdir, exist_ok=True)

    try:
        import pymupdf  # PyMuPDF >= 1.24; older releases call it fitz
    except ImportError:
        try:
            import fitz as pymupdf  # older API compatibility
        except ImportError:
            die("pymupdf is missing, so pages cannot be extracted. Install it:\n"
                "    <your python.exe>/pip install pymupdf\n"
                "  (note: the python3 on your PATH does not necessarily have the package installed; let precheck.mjs pick a good one for you)")
    except Exception as e:
        die("importing pymupdf raised: %r" % (e,))

    try:
        doc = pymupdf.open(pdf)
    except Exception as e:
        die("Cannot open PDF %s: %r\n  Usually means encrypted or corrupt — re-export it from Office/WPS first." % (pdf, e))

    if doc.needs_pass:
        die("This PDF is password-protected, so pages cannot be extracted. Remove the password and export it again.")

    n = doc.page_count
    if n == 0:
        die("The PDF has 0 pages, so there is nothing to extract.")

    zoom = a.dpi / 72.0
    wrote, texts = [], []
    for i, page in enumerate(doc, start=1):
        tag = "%02d" % i
        pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        w, h = pm.width, pm.height
        need = max(w, h)
        z2 = zoom
        if a.scale_to:
            # force the long edge to --scale-to: scale up/down proportionally to the target pixel count
            z2 = float(a.scale_to) / need if need else zoom
        elif a.min_dpi and need < a.min_dpi:
            # the page itself is small (A5 portrait, say) -> lift it to the floor long edge instead of extracting a
            # small image that downstream would enlarge into mush
            z2 = zoom * (float(a.min_dpi) / need)
        if abs(z2 - zoom) > 1e-6:
            pm = page.get_pixmap(matrix=pymupdf.Matrix(z2, z2), alpha=False)
        p = os.path.join(outdir, tag + ".png")
        pm.save(p)
        wrote.append((tag, pm.width, pm.height))
        t = page.get_text("text").strip()
        texts.append("===== Page %d =====\n%s" % (i, t if t else "(no text layer)"))
        print("[PAGE] %s  %dx%d  %s" % (tag, pm.width, pm.height,
                                        "has text" if t else "no text layer"), flush=True)

    # source.txt: for checking page by page while writing the narration. Blank-line separated, as before.
    src_txt = os.path.join(job, "source.txt")
    with open(src_txt, "w", encoding="utf-8") as f:
        f.write("\n\n".join(texts) + "\n")

    doc.close()

    # Aspect-ratio consistency check: mismatched ratios -> downstream padding adds black bars, which reads as "the picture drifts".
    # This only warns, it never blocks (some decks genuinely mix ratios), but it has to be visible.
    ratios = {}
    for tag, w, h in wrote:
        ratios.setdefault(round(w / h, 3), []).append(tag)
    warn = ""
    if len(ratios) > 1:
        detail = "; ".join("%.3f(%s)" % (k, ",".join(v[:6]) + ("..." if len(v) > 6 else ""))
                           for k, v in sorted(ratios.items(), reverse=True))
        warn = ("\n[NOTICE] this PDF has %d different page aspect ratios: %s\n"
                "       Downstream everything is scaled and padded to 1920x1080, so pages with other ratios will carry black bars. "
                "If the source PPT itself mixes ratios that is expected; if they should all match, go back and check the PPT master settings."
                % (len(ratios), detail))

    meta = os.path.join(job, "pdf", "pages_meta.json")
    os.makedirs(os.path.dirname(meta), exist_ok=True)
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"pdf": pdf, "pages": len(wrote),
                   "size": {t: [w, h] for t, w, h in wrote},
                   "ratios": {str(k): v for k, v in ratios.items()}},
                  f, ensure_ascii=False, indent=2)

    print("\nDone: %d pages -> %s" % (len(wrote), outdir))
    print("Text -> %s (check page by page while writing the narration)" % src_txt)
    print("Size distribution -> %s" % meta)
    if warn:
        print(warn)
    print("\nNext: write the per-page narration as NN.txt inside vo3/, then run gen_sentence_ass.py")


if __name__ == "__main__":
    main()
