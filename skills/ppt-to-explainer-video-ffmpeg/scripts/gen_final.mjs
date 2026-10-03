// gen_final.mjs — 成片合成,两种模式
//
//   --mode concat  【新·推荐】三段式:段不烧字幕 -> -c copy 硬切拼接 -> 单遍烧字幕
//                  实测(50 页 7:47 片): 段渲染 41.7s(并行 j=4) + 硬切 1.4s + 烧字幕 47.5s(medium)
//                  对比旧做法(段内烧字幕 + 49 级 xfade): 65s + 63s = 128s  →  总耗时约 -30%
//                  额外好处:master.mp4 是"无字幕母版",改片头/换字幕版不必重新配音,拼 master 本身 0 编码。
//
//   --mode xfade   【旧·兼容】段内已烧字幕,再做 N-1 级 xfade/acrossfade 交叉淡入。
//
// 2026-10-02 修复:ffmpeg 路径 / 段名前缀 / 输出名 / 转场时长 全部可传,不再硬编码;
//               durations2.txt 缺失时给的是「先跑哪一步」的人话,不是裸 ENOENT 堆栈。
//
// 用法(新三段式):
//   node gen_final.mjs --job . --mode concat --seg seg --ass all.ass --out 成片.mp4
//   node gen_final.mjs --job . --mode xfade --seg seg --out 成片.mp4
import { readFileSync, writeFileSync, existsSync, accessSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

function arg(k, d) {
  const i = process.argv.indexOf("--" + k);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : d;
}
const JOB = arg("job", process.cwd()).replace(/\\/g, "/");
// ffmpeg 自动探测(PATH 优先),避免把某个机器的绝对路径固化进去;始终可用 --ff 覆盖
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
const OUT = arg("out", "成片.mp4");
const MASTER = arg("master", "master.mp4");
const INTRO = arg("intro", "");           // 片头 mp4(无音轨或带音轨都行)
const INTRO_T = parseFloat(arg("intro-t", "0.5"));  // 0 = 硬切(走 -c copy)
const PRESET = arg("preset", "medium");
const CRF = arg("crf", "20");
const T = parseFloat(arg("transition", "0.5"));

function die(msg) {
  console.error("[错误] " + msg);
  process.exit(1);
}

const dp = join(JOB, DUR);
if (!existsSync(dp)) {
  die(`找不到 ${DUR}。它是渲染阶段产出的每页时长表,先跑:
     python <技能>/scripts/render_all.py --job <JOBDIR> --rows durations.json --j 4
   (render_all.py 结束后会把这张表写成 durations2.txt)`);
}

const items = readFileSync(dp, "utf8").trim().split(/\r?\n/).filter(Boolean).map((l) => {
  const [nn, d] = l.split("=");
  return { nn: nn.trim(), d: parseFloat(d) };
});
if (items.length < 2) die(`durations2.txt 只有 ${items.length} 段,至少要 2 段才能拼。`);

const N = items.length; // 在 concat / xfade 两个分支之外声明,两个模式都要用
const segList = items.map((it) => `file '${SEG}/${it.nn}.mp4'`).join("\n") + "\n";
const concatList = join(JOB, "concat_list.txt");
writeFileSync(concatList, segList);

const inputs = items.map((it) => `-i "${SEG}/${it.nn}.mp4"`).join(" ");
const sh = [];

if (MODE === "concat") {
  // concat 模式下片头直接进 concat_list(硬切,-c copy,0 重编码)。
  // ⚠️ concat 要求各段流一致:片头 mp4 必须带一条**静音音轨**,否则输出会丢音频。
  //   生成片头时加 -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -shortest
  const files = items.map((it) => `file '${SEG}/${it.nn}.mp4'`);
  if (INTRO) {
    // 传了 --intro 却找不到文件:必须报错退出。
    // 否则 existsSync 判空会整段跳过,成片静默丢片头还不吭声。
    if (!existsSync(join(JOB, INTRO))) {
      console.error(`[错误] 找不到片头 ${INTRO} —— 先生成它(要用 anullsrc 做一条实长静音音轨,` +
        `配合 -c copy 硬切,否则输出会丢音频)。`);
      process.exit(1);
    }
    if (INTRO_T > 0) {
      // 要交叉淡入就必须整片重编一遍(比硬切多 ~79s/7分钟片),非必要别开
      const off = (parseFloat(arg("intro-dur", "3")) - INTRO_T).toFixed(3);
      sh.push(`"${FF}" -y -f concat -safe 0 -i concat_list.txt -c copy "${MASTER}"`);
      sh.push(`"${FF}" -y -i "${INTRO}" -i "${MASTER}" ` +
        `-filter_complex "[0:v]scale=1920:1080:fps=30,format=yuv420p[v0];[1:v]scale=1920:1080:fps=30,format=yuv420p[v1];` +
        `[v0][v1]xfade=transition=fade:duration=${INTRO_T}:offset=${off}[vo]" ` +
        `-map "[vo]" -map 1:a -c:v libx264 -preset ${PRESET} -crf ${CRF} -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k "${MASTER}"`);
    } else {
      files.unshift(`file '${INTRO}'`); // 硬切片头:进 concat_list,零重编码
    }
  }
  writeFileSync(concatList, files.join("\n") + "\n");
  // 1) 硬切拼接母版(不重编码)
  sh.unshift(`"${FF}" -y -f concat -safe 0 -i concat_list.txt -c copy "${MASTER}"`);
  // 3) 单遍烧字幕(这是唯一一次全片重编码)
  sh.push(`"${FF}" -y -i "${MASTER}" -vf "subtitles='${ASS.split("/").pop()}'" ` +
    `-c:v libx264 -preset ${PRESET} -crf ${CRF} -pix_fmt yuv420p -r 30 -c:a copy "${OUT}"`);
} else {
  // 旧:段内已烧字幕 + N-1 级 xfade
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
console.log(`模式=${MODE} 段数=${N} 预计时长≈${(items.reduce((a, b) => a + b.d, 0) - (MODE === "xfade" ? (N - 1) * T : 0)).toFixed(1)}s`);
console.log("已写 " + path + " —— 用 Bash 工具执行它(别在 Node 里 spawn ffmpeg)。");
