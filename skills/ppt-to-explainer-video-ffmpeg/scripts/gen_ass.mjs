// gen_ass.mjs — 把每页 NN.txt 旁白文案转成 ASS 字幕(默认写进 ass/ 子目录),供 ffmpeg 硬烧。
//
// 2026-10-02 修复:
//   1) 【静默损坏】旧版直接把 "\n" 拼进 Dialogue 行 -> 第二行缺 Dialogue: 头,libass 解析失败,
//      该页字幕整条消失且脚本仍报 "DONE ass=N"。现在换行一律转成 ASS 硬换行标记 \N。
//   2) 样式默认值 BorderStyle 改成 3(半透明黑底):旧版 1(纯描边)在有底色的 PPT 页上会被吃掉。
//   3) 参数全部可传(--size/--font/--border/--align/--mv/--outline),不再是写死的 SimHei 40px。
//   4) --outdir 默认 ass/,不再把 .ass 丢在和 .txt 同一层。
//
// 用法: node gen_ass.mjs --job <JOBDIR> [--mode static|scroll] [--size 60] [--y 900]
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
const BORDER = arg("border", "3");           // 0=描边 3=半透明黑底+描边
const OUTLINE = arg("outline", "3");
const SHADOW = arg("shadow", "0");
const ALIGN = arg("align", "2");            // 2=底部居中;滚动字幕用 7(左上)
const MV = arg("mv", "90");
const MODE = arg("mode", "static");

function esc(s) {
  return s.replace(/\\/g, "\\\\").replace(/,/g, "\\,").replace(/\{/g, "\\{").replace(/\}/g, "\\}");
}

// 换行必须是 ASS 硬换行 \N,不能是裸 \n。
// ⚠️ 顺序:先逐行 esc,再用字面的 \N 连接 —— 如果先拼 \N 再整体 esc,
//    esc 会把 \N 里的反斜杠变成 \\N,ASS 里就只剩一个字面反斜杠 + 字母 N(实测踩过)。
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
  // 单条事件:整页时长由 all.ass / --durations 决定,这里给 9:59:59.99 占位
  const ass = head + `Dialogue: 0,0:00:00.00,9:59:59.99,Default,,0,0,0,,${esc(body)}\n`;
  writeFileSync(join(OUT, `${nn}.ass`), ass, "utf8");
  n++;
}
console.log(`DONE ass=${n} 目录=${OUT} 含换行的页=${multi} BorderStyle=${BORDER}`);
if (multi) console.log("提示:含 \N 换行的页已按 ASS 硬换行处理(旧版会静默丢字幕)");
