// gen_srt.mjs — generate a standalone srt (timeline includes transition compensation / intro offset)
//
// 2026-10-02 fixes:
//   1) A missing NN.txt no longer yields a bare ENOENT stack but tells you which step to run first.
//   2) By default it emits a **sentence-level** srt from bounds_cache.json (matching the burned-in sentence-level subtitles);
//      --source page falls back to the old "one cue per page" behavior.
//   3) Sentence overlaps are trimmed with prev_end (the old version wrote a broken srt with crossing start and end times).
//   4) The output carries a UTF-8 BOM so CJK players don't show mojibake.
//   5) --intro / --t / --src-dir / --durations are all passable, no longer hard-coded.
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
const OUT = arg("out", "final.srt");
const INTRO = parseFloat(arg("intro", "0"));
const T = parseFloat(arg("t", "0.5"));
const SRC = arg("source", "auto"); // auto | bounds | page

const dp = join(JOB, DUR);
if (!existsSync(dp)) {
  console.error("[ERROR] cannot find " + DUR + ". Run render_all.py first to generate the duration table.");
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
let outEnd = 0; // end time of the previous srt cue, used to trim overlaps (must be initialized before forEach)

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
      if (a < outEnd) a = outEnd; // trim the overlap introduced by TTS boundaries
      if (b <= a) continue;
      out += `${cues + 1}\n${fmt(a)} --> ${fmt(b)}\n${txt}\n\n`;
      outEnd = b;
      cues++;
    }
    return;
  }

  const txtp = join(JOB, TXT, it.nn + ".txt");
  if (!existsSync(txtp)) {
    console.error(`[SKIP] ${txtp} does not exist — write the per-page narration first.`);
    return;
  }
  const text = readFileSync(txtp, "utf8").trim().replace(/\r?\n/g, " ");
  out += `${cues + 1}\n${fmt(Math.max(start, 0))} --> ${fmt(end - 0.35)}\n${text}\n\n`;
  cues++;
});

writeFileSync(join(JOB, OUT), out, "utf8");
console.log(`wrote ${OUT}, ${cues} cues, intro=${INTRO}s`);
