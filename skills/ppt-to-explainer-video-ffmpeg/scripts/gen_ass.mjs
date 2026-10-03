// gen_ass.mjs — turns each page's NN.txt narration script into ASS subtitles (written to the ass/ subdirectory by default) for ffmpeg to burn in.
//
// 2026-10-02 fixes:
//   1) [silent corruption] The old version spliced "\n" straight into the Dialogue line -> the second line had no Dialogue: header, libass failed
//      to parse it, that page's subtitle vanished entirely and the script still reported "DONE ass=N". Newlines are now always converted into the
//      ASS hard line-break marker \N.
//   2) The style's default BorderStyle is now 3 (semi-transparent black box): the old 1 (outline only) was swallowed on PPT pages with a colored background.
//   3) Every parameter can now be passed in (--size/--font/--border/--align/--mv/--outline); no more hard-coded SimHei 40px.
//   4) --outdir defaults to ass/, so .ass files are no longer dumped next to the .txt files.
//
// Usage: node gen_ass.mjs --job <JOBDIR> [--mode static|scroll] [--size 60] [--y 900]
import { readFileSync, writeFileSync, readdirSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

function arg(k, d) {
  const i = process.argv.indexOf("--" + k);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : d;
}
const JOB = arg("job", process.cwd());
const OUT = arg("outdir", join(JOB, "ass"));
const SIZE = arg("size", "60");
const FONTNAME = arg("font", "SimHei");
const BORDER = arg("border", "3");           // 0=outline 3=semi-transparent black box + outline
const OUTLINE = arg("outline", "3");
const SHADOW = arg("shadow", "0");
const ALIGN = arg("align", "2");            // 2=bottom center; use 7 (top left) for scrolling subtitles
const MV = arg("mv", "90");
const MODE = arg("mode", "static");

function esc(s) {
  return s.replace(/\\/g, "\\\\").replace(/,/g, "\\,").replace(/\{/g, "\\{").replace(/\}/g, "\\}");
}

// Newlines must be the ASS hard line break \N, never a bare \n.
// ⚠️ Order matters: esc line by line first, then join with a literal \N — if you join \N first and esc the whole thing afterwards,
//    esc turns the backslash inside \N into \\N, leaving only a literal backslash + the letter N in the ASS (measured the hard way).
function toAssBody(text) {
  const lines = text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  if (!lines.length) return null;
  return lines.map(esc).join("\\N");
}

const style = `Style: Default,${FONTNAME},${SIZE},&H00FFFFFF,&H000000FF,&H00000000,&HCC000000,1,0,0,0,100,100,0,0,${BORDER},${OUTLINE},${SHADOW},${ALIGN},60,60,${MV},1`;
const head = `[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: ${MODE === "scroll" ? 2 : 0}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
${style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;

const files = readdirSync(JOB).filter((f) => /^\d{2}\.txt$/.test(f)).sort();
mkdirSync(OUT, { recursive: true });
let n = 0, multi = 0;
for (const f of files) {
  const nn = f.replace(/\.txt$/, "");
  const raw = readFileSync(join(JOB, f), "utf8").trim();
  if (!raw) continue;
  const body = toAssBody(raw);
  if (!body) continue;
  if (body.includes("\\N")) multi++;
  // Single event: the full-page duration comes from all.ass / --durations, so 9:59:59.99 is just a placeholder here
  const ass = head + `Dialogue: 0,0:00:00.00,9:59:59.99,Default,,0,0,0,,${esc(body)}\n`;
  writeFileSync(join(OUT, `${nn}.ass`), ass, "utf8");
  n++;
}
console.log(`DONE ass=${n} outdir=${OUT} pages_with_line_breaks=${multi} BorderStyle=${BORDER}`);
if (multi) console.log("Note: pages containing \N line breaks were handled as ASS hard line breaks (the old version silently dropped their subtitles)");
