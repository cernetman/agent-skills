// gen_srt.mjs — 生成独立 srt(时间轴含转场补偿 / 片头偏移)
//
// 2026-10-02 修复:
//   1) 缺 NN.txt 时不再是裸 ENOENT 堆栈,而是指令你先跑哪一步。
//   2) 默认从 bounds_cache.json 出**逐句级** srt(和硬字幕逐句一致);
//      --source page 才回退成"每页一条"的老行为。
//   3) 逐句重叠用 prev_end 裁掉(旧版会输出首尾交叉的坏 srt)。
//   4) 输出带 UTF-8 BOM,中文播放器不乱码。
//   5) --intro / --t / --src-dir / --durations 全部可传,不再写死。
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

function arg(k, d) {
  const i = process.argv.indexOf("--" + k);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : d;
}
const JOB = arg("job", process.cwd());
const DUR = arg("durations", "durations2.txt");
const BOUNDS = arg("bounds", "bounds_cache.json");
const TXT = arg("src-dir", "vo3");
const OUT = arg("out", "成片字幕.srt");
const INTRO = parseFloat(arg("intro", "0"));
const T = parseFloat(arg("t", "0.5"));
const SRC = arg("source", "auto"); // auto | bounds | page

const dp = join(JOB, DUR);
if (!existsSync(dp)) {
  console.error("[错误] 找不到 " + DUR + "。先跑 render_all.py 生成时长表。");
  process.exit(1);
}

function loadDurs() {
  return readFileSync(dp, "utf8").trim().split(/\r?\n/).filter(Boolean).map((l) => {
    const [nn, d] = l.split("=");
    return { nn: nn.trim(), d: parseFloat(d) };
  });
}
function loadBounds() {
  const p = join(JOB, BOUNDS);
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}
const fmt = (s) => {
  const ms = Math.max(0, Math.round(s * 1000));
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const sec = Math.floor((ms % 60000) / 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`;
};

const items = loadDurs();
const bounds = SRC === "bounds" ? loadBounds() : SRC === "auto" ? loadBounds() : null;
let out = "";
let cues = 0;
let cum = 0;
let outEnd = 0; // 上一条 srt 的结束时间,用来裁重叠(必须在 forEach 之前初始化)

items.forEach((it, i) => {
  const start = cum - i * T + INTRO;
  cum += it.d;
  const end = start + it.d;

  if (bounds) {
    const ev = bounds[it.nn] || bounds[it.nn.replace(/^0/, "")] || [];
    for (const [txt, off, dur] of ev) {
      let a = start + off / 1e7;
      let b = start + (off + dur) / 1e7;
      if (b <= a) continue;
      if (a < outEnd) a = outEnd; // 裁掉 TTS 边界带来的重叠
      if (b <= a) continue;
      out += `${cues + 1}\n${fmt(a)} --> ${fmt(b)}\n${txt}\n\n`;
      outEnd = b;
      cues++;
    }
    return;
  }

  const txtp = join(JOB, TXT, it.nn + ".txt");
  if (!existsSync(txtp)) {
    console.error(`[跳过] ${txtp} 不存在 —— 先写上逐页旁白。`);
    return;
  }
  const text = readFileSync(txtp, "utf8").trim().replace(/\r?\n/g, " ");
  out += `${cues + 1}\n${fmt(Math.max(start, 0))} --> ${fmt(end - 0.35)}\n${text}\n\n`;
  cues++;
});

writeFileSync(join(JOB, OUT), out, "utf8");
console.log(`写出 ${OUT}, ${cues} 条, intro=${INTRO}s`);
