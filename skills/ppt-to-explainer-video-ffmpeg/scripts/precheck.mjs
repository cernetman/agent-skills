// precheck.mjs — preflight check before starting, turning "it blows up halfway through" into "you know from the outset what's missing"
//
// Added 2026-10-02. Real pitfalls hit in practice:
//   - the python3 on PATH is 3.14.3 and has **no edge_tts**; the interpreter that actually has the package installed is 3.13.12.
//     Copying `python3 -m edge_tts` gives you an immediate ModuleNotFoundError.
//   - ffmpeg / ffprobe are hard dependencies of this skill; missing either one breaks the whole pipeline.
//
// 2026-10-07 Added in v2.0.0 (the PPT -> PDF stage brings a batch of new dependencies):
//   - pymupdf: step 1's PDF page-image extraction depends on it (the old flow used python-pptx, no longer needed).
//   - LibreOffice (soffice): step 0's PPT/Word -> PDF depends on it.
//     **It has to be judged inside the same interpreter environment as edge_tts / pymupdf**, otherwise you get
//     "step 0 produced the PDF, but step 1 can't extract the pages" — a broken chain halfway through.
//   - source PDF / page images are reported as two separate rows: PDF but no page images = stuck at step 1,
//     neither = stuck at step 0.
//
// Usage: node precheck.mjs [--job .] [--py <path to python.exe>] [--pdf pdf/source.pdf] [--soffice <path>]
import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";

function arg(k, d) {
  const i = process.argv.indexOf("--" + k);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : d;
}
// Candidate path probing (PATH first) — don't hard-code one machine's absolute paths, or it stops working on another machine.
// Nothing here spawns an external process; only existsSync.
const JOB = arg("job", process.cwd());
const firstOf = (cands) => { for (const c of cands) if (existsSync(c)) return c; return ""; };
const FF = arg("ff", firstOf(["/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg",
  "C:/Program Files/ffmpeg/bin/ffmpeg.exe", join(homedir(), "bin/ffmpeg.exe")]) || "ffmpeg");
const FONT = arg("font", firstOf(["C:/Windows/Fonts/simhei.ttf",
  "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
  "/System/Library/Fonts/PingFang.ttc"]) || "C:/Windows/Fonts/simhei.ttf");

const rows = [];
const ok = (n, c, tip, extra = "") => rows.push([c ? "OK  " : "FAIL", n, extra, tip]);

// 1) ffmpeg — only checks whether it can be resolved.
// ⚠️ Don't use Node spawn to run ffmpeg: on this machine spawning external processes from Node is blocked by the sandbox (EBUSY / no output),
//    and the check would tie itself in knots. So this only resolves the path; for real availability run once through Bash: <FF> -version
const resolved = (p) => (existsSync(p) ? p : (p.includes("/") || p.includes("\\") ? "" : p)); // bare name = resolvable via PATH
const ffFound = resolved(FF);
ok("ffmpeg", !!ffFound, FF, ffFound
  ? "resolvable; for real availability run once through Bash: " + FF + " -version"
  : "download it from https://ffmpeg.org, or make sure --ff points at the right path");
// 2) ffprobe (segment durations depend on it): lives in the same directory as ffmpeg, or a bare name when ffmpeg is on PATH
const probeName = FF.toLowerCase().endsWith(".exe") ? "ffprobe.exe" : "ffprobe";
const ffprobe = arg("ffprobe", FF.endsWith(probeName) ? FF : FF.replace(/ffmpeg(\.exe)?$/, "") + probeName);
const prFound = resolved(ffprobe);
ok("ffprobe", !!prFound, ffprobe, prFound ? "" : ffFound ? "normally installed alongside ffmpeg in the same directory" : "install ffmpeg first, then come back to this row");
// 3) CJK font
const fontFound = resolved(FONT);
ok("CJK font", !!fontFound, FONT, fontFound ? "" : "install SimHei, or point --font at another .ttf");
// 4) edge_tts: probe every candidate interpreter first
const pys = [];
const extra = arg("py", "");
if (extra) pys.push(extra);
try {
  pys.push(execFileSync("where", ["python"], { encoding: "utf8" }).trim().split(/\r?\n/)[0]);
} catch {}
// The places the WorkBuddy-managed python may live (uses homedir instead of hard-coding one machine)
globDir(join(homedir(), ".workbuddy/binaries/python/versions"))
  .forEach((d) => pys.push(join(d, "python.exe")));
function globDir(dir) {
  try { return readdirSync(dir).map((d) => join(dir, d)); } catch { return []; }
}
let hit = "";
for (const p of [...new Set(pys)]) {
  if (!existsSync(p)) continue;
  try {
    execFileSync(p, ["-c", "import edge_tts"], { encoding: "utf8", stdio: "ignore" });
    hit = p;
    break;
  } catch {}
}
ok("edge_tts", !!hit, hit || "none of the candidate python installs has edge_tts",
  hit ? "" : "use the python that has the package installed: " +
  `<your python>/pip install edge-tts — note that the python3 on PATH is not necessarily that one,` +
  "so prefer calling it by absolute path everywhere");
// 4b) [added in v2.0.0] pymupdf — page-image extraction from PDF depends on it (step 1, pdf_to_pages.py)
let pmHit = "";
for (const p of [...new Set(pys)]) {
  if (!existsSync(p)) continue;
  try {
    // the new API is pymupdf, older versions are fitz — probe both
    execFileSync(p, ["-c", "import pymupdf"], { encoding: "utf8", stdio: "ignore" });
    pmHit = p;
    break;
  } catch {
    try {
      execFileSync(p, ["-c", "import fitz"], { encoding: "utf8", stdio: "ignore" });
      pmHit = p + " (fitz legacy API)";
      break;
    } catch {}
  }
}
ok("pymupdf", !!pmHit, pmHit ? pmHit.replace(" (fitz legacy API)", "") : "no python with pymupdf installed was found",
  pmHit ? "" : "page-image extraction from PDF depends on it: <your python>/pip install pymupdf" +
  " (install it in the same interpreter as edge_tts, or step 0 will produce the PDF but step 1 won't be able to extract the pages)");
// 4c) [added in v2.0.0] LibreOffice — only required when the source file is PPT/Word.
//     A project that already has the PDF can do without it (go straight to step 1).
const SOF = arg("soffice", firstOf([
  "C:/Program Files/LibreOffice/program/soffice.com",
  "C:/Program Files/LibreOffice/program/soffice.exe",
  "C:/Program Files (x86)/LibreOffice/program/soffice.com",
  "/usr/bin/soffice", "/usr/local/bin/soffice", "/snap/bin/libreoffice",
  "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]) || "");
const sofResolved = SOF ? resolved(SOF) : "";
const hasPdf = existsSync(join(JOB, arg("pdf", "pdf/source.pdf")));
if (sofResolved || hasPdf) {
  ok("LibreOffice", !!sofResolved, sofResolved || "(already have the PDF, not needed)",
    sofResolved ? (hasPdf ? "" : "ready — just remember to run to_pdf.py before extracting page images")
      : "");
} else {
  ok("LibreOffice", false, "no soffice found, and no pdf/source.pdf yet",
    "PPT/Word has to go through to_pdf.py to become a PDF. Install LibreOffice: https://www.libreoffice.org/download/" +
    " | or save as PDF by hand with Office/WPS, then --input \"<that.pdf>\" goes straight to step 1");
}
// 5) page images — upstream is now always a PDF, so report the intermediate artifact too
const pagesDir = arg("pages", "pages");
const pdfRel = arg("pdf", "pdf/source.pdf");
const pdfP = join(JOB, pdfRel);
const pdfOk = existsSync(pdfP);
const pn = existsSync(join(JOB, pagesDir)) ? readdirSync(join(JOB, pagesDir)).filter((f) => /\.(png|jpg)$/i.test(f)).length : 0;
ok("source PDF", pdfOk, pdfP, pdfOk ? "ready (step 0 output)" :
  "not there yet — run first: python <skill>/scripts/to_pdf.py --input \"<source file>\" --job .");
ok("page images", pn > 0, join(JOB, pagesDir), pn ? `${pn} found` :
  "run pdf_to_pages.py first (PDF -> pages/NN.png); don't go back to pulling pages straight out of the PPT with python-pptx and friends — the frames come out off");
// 6) disk budget (informational only, never fails the check)
//    Node cannot read free space on Windows, so estimate it from the final bitrate instead:
//    1080p 30fps crf20 is about 1.9 Mbps ≈ duration (seconds) × 0.22 MB
const mc = arg("minutes", "");
if (mc) {
  const est = parseFloat(mc) * 60 * 0.22;
  ok("disk budget", est < 5000, "estimated film size", `${mc} min ≈ ${est.toFixed(0)} MB`);
}

const bad = rows.filter((r) => r[0] === "FAIL");
console.log("\n=== Preflight check ===");
for (const [s, n, loc, tip] of rows) {
  console.log(`${s === "OK  " ? "✅" : "❌"} ${n.padEnd(10)} ${loc}${tip ? "\n    ↳ " + tip : ""}`);
}
console.log(`\ntotal ${rows.length} checks, ${bad.length} failed${bad.length ? " — fix them before starting" : " — ready to start"}\n`);
if (bad.length) process.exit(2);
