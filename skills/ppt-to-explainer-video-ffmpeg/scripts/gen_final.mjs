// gen_final.mjs — final film assembly, two modes
//
//   --mode concat  [new · recommended] three-stage: segments stay subtitle-free -> hard-cut concat with -c copy -> single-pass subtitle burn
//                  measured (50 pages, 7:47 film): segment rendering 41.7s (parallel j=4) + hard cut 1.4s + subtitle burn 47.5s (medium)
//                  versus the old approach (burn inside segments + 49 levels of xfade): 65s + 63s = 128s  →  about -30% total time
//                  extra benefit: master.mp4 is a "subtitle-free master", so changing the intro or swapping subtitle versions needs no
//                  re-recording, and building master itself costs 0 encodes.
//
//   --mode xfade   [old · legacy] subtitles were already burned inside the segments, then N-1 levels of xfade/acrossfade cross-fade.
//
// 2026-10-02 fixes: ffmpeg path / segment name prefix / output name / transition duration are all passable, no longer hard-coded;
//               when durations2.txt is missing you get plain-language advice about which step to run first, not a bare ENOENT stack.
//
// Usage (new three-stage):
//   node gen_final.mjs --job . --mode concat --seg seg --ass all.ass --out final.mp4
//   node gen_final.mjs --job . --mode xfade --seg seg --out final.mp4
import { readFileSync, writeFileSync, existsSync, accessSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

function arg(k, d) {
  const i = process.argv.indexOf("--" + k);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : d;
}
const JOB = arg("job", process.cwd()).replace(/\\/g, "/");
// ffmpeg auto-detection (PATH first) so no single machine's absolute path gets baked in; --ff always overrides
const firstOf = (cands, fallback = "ffmpeg") => {
  for (const c of cands) {
    try { accessSync(c); return c; } catch {}
  }
  return fallback;
};
const FF = arg("ff", firstOf(["/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg", "ffmpeg",
  "C:/Program Files/ffmpeg/bin/ffmpeg.exe", join(homedir(), "bin/ffmpeg.exe")])).replace(/\\/g, "/");
const MODE = arg("mode", "concat");
const SEG = arg("seg", "seg");
const DUR = arg("durations", "durations2.txt");
const ASS = arg("ass", "all.ass");
const OUT = arg("out", "final.mp4");
const MASTER = arg("master", "master.mp4");
const INTRO = arg("intro", "");           // intro mp4 (with or without an audio track)
const INTRO_T = parseFloat(arg("intro-t", "0.5"));  // 0 = hard cut (goes through -c copy)
const PRESET = arg("preset", "medium");
const CRF = arg("crf", "20");
const T = parseFloat(arg("transition", "0.5"));

function die(msg) {
  console.error("[ERROR] " + msg);
  process.exit(1);
}

const dp = join(JOB, DUR);
if (!existsSync(dp)) {
  die(`cannot find ${DUR}. It is the per-page duration table produced by the rendering stage, so run this first:
     python <skill>/scripts/render_all.py --job <JOBDIR> --rows durations.json --j 4
   (render_all.py writes this table out as durations2.txt when it finishes)`);
}

const items = readFileSync(dp, "utf8").trim().split(/\r?\n/).filter(Boolean).map((l) => {
  const [nn, d] = l.split("=");
  return { nn: nn.trim(), d: parseFloat(d) };
});
if (items.length < 2) die(`durations2.txt only has ${items.length} segments; at least 2 are needed to concat.`);

const N = items.length; // declared outside both the concat and xfade branches, since both modes need it
const segList = items.map((it) => `file '${SEG}/${it.nn}.mp4'`).join("\n") + "\n";
const concatList = join(JOB, "concat_list.txt");
writeFileSync(concatList, segList);

const inputs = items.map((it) => `-i "${SEG}/${it.nn}.mp4"`).join(" ");
const sh = [];

if (MODE === "concat") {
  // In concat mode the intro goes straight into concat_list (hard cut, -c copy, 0 re-encodes).
  // ⚠️ concat requires identical streams across all segments: the intro mp4 must carry a **silent audio track**, otherwise the output loses audio.
  //   When generating the intro, add -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -shortest
  const files = items.map((it) => `file '${SEG}/${it.nn}.mp4'`);
  if (INTRO) {
    // --intro was passed but the file is missing: this has to fail loudly.
    // Otherwise existsSync returning false silently skips the whole block, and the film loses its intro without a word.
    if (!existsSync(join(JOB, INTRO))) {
      console.error(`[ERROR] cannot find the intro ${INTRO} — generate it first (use anullsrc to build a real-length silent audio track ` +
        `so it survives the -c copy hard cut, otherwise the output loses audio).`);
      process.exit(1);
    }
    if (INTRO_T > 0) {
      // A cross-fade means re-encoding the whole film (~79s more for a 7-minute film than a hard cut); don't enable it unless you need it
      const off = (parseFloat(arg("intro-dur", "3")) - INTRO_T).toFixed(3);
      sh.push(`"${FF}" -y -f concat -safe 0 -i concat_list.txt -c copy "${MASTER}"`);
      sh.push(`"${FF}" -y -i "${INTRO}" -i "${MASTER}" ` +
        `-filter_complex "[0:v]scale=1920:1080:fps=30,format=yuv420p[v0];[1:v]scale=1920:1080:fps=30,format=yuv420p[v1];` +
        `[v0][v1]xfade=transition=fade:duration=${INTRO_T}:offset=${off}[vo]" ` +
        `-map "[vo]" -map 1:a -c:v libx264 -preset ${PRESET} -crf ${CRF} -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k "${MASTER}"`);
    } else {
      files.unshift(`file '${INTRO}'`); // hard-cut intro: goes into concat_list, zero re-encodes
    }
  }
  writeFileSync(concatList, files.join("\n") + "\n");
  // 1) hard-cut concat the master (no re-encode)
  sh.unshift(`"${FF}" -y -f concat -safe 0 -i concat_list.txt -c copy "${MASTER}"`);
  // 3) single-pass subtitle burn (the only full-film re-encode)
  sh.push(`"${FF}" -y -i "${MASTER}" -vf "subtitles='${ASS.split("/").pop()}'" ` +
    `-c:v libx264 -preset ${PRESET} -crf ${CRF} -pix_fmt yuv420p -r 30 -c:a copy "${OUT}"`);
} else {
  // legacy: subtitles already burned inside the segments + N-1 levels of xfade
  const vparts = [];
  let cum = 0;
  for (let k = 1; k < N; k++) {
    cum += items[k - 1].d;
    const off = (cum - k * T).toFixed(3);
    vparts.push(`${k === 1 ? "[0:v]" : "[v" + (k - 1) + "]"}[${k}:v]xfade=transition=fade:duration=${T}:offset=${off}${k === N - 1 ? "[vout]" : "[v" + k + "]"}`);
  }
  const aparts = [];
  for (let k = 1; k < N; k++) {
    aparts.push(`${k === 1 ? "[0:a]" : "[a" + (k - 1) + "]"}[${k}:a]acrossfade=d=${T}${k === N - 1 ? "[aout]" : "[a" + k + "]"}`);
  }
  const fc = [...vparts, ...aparts].join(";");
  sh.push(`"${FF}" -y ${inputs} -filter_complex "${fc}" -map "[vout]" -map "[aout]" ` +
    `-c:v libx264 -preset ${PRESET} -crf ${CRF} -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k -ar 44100 "${OUT}"`);
}

const path = join(JOB, "render_final.sh");
writeFileSync(path, "#!/bin/bash\ncd \"" + JOB + "\"\n" + sh.join("\n") + "\n", "utf8");
console.log(`mode=${MODE} segments=${N} estimated duration≈${(items.reduce((a, b) => a + b.d, 0) - (MODE === "xfade" ? (N - 1) * T : 0)).toFixed(1)}s`);
console.log("wrote " + path + " — execute it with the Bash tool (do not spawn ffmpeg from inside Node).");
