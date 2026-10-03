// precheck.mjs — 开工前环境自检,把"跑到一半才炸"变成"开局就知道缺啥"
//
// 2026-10-02 新增。实测踩到的真实坑:
//   - PATH 里的 python3 是 3.14.3,**没有 edge_tts**;实际装包的是 3.13.12。
//     照抄 `python3 -m edge_tts` 会直接 ModuleNotFoundError。
//   - ffmpeg / ffprobe 是本技能强依赖,缺一个整条管线就断。
//
// 用法: node precheck.mjs [--job .] [--py <python.exe 路径>]
import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";

function arg(k, d) {
  const i = process.argv.indexOf("--" + k);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : d;
}
// 候选路径探测(PATH 优先)——别把某一台机器的绝对路径写死,换机器就跑不动。
// 全程不 spawn 外部进程,只做 existsSync。
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

// 1) ffmpeg —— 只查"能不能解析到"。
// ⚠️ 别用 Node spawn 去跑 ffmpeg:本机 Node spawn 外部进程会被沙箱挡(EBUSY / 无输出),
//    自检会把自己绕死。所以这里只做路径解析,真实可用性建议用 Bash 跑一次: <FF> -version
const resolved = (p) => (existsSync(p) ? p : (p.includes("/") || p.includes("\\") ? "" : p)); // 裸名=PATH 可解析
const ffFound = resolved(FF);
ok("ffmpeg", !!ffFound, FF, ffFound
  ? "可解析;实际可用性建议用 Bash 跑一次: " + FF + " -version"
  : "去 https://ffmpeg.org 下载,或确认 --ff 指向正确路径");
// 2) ffprobe(段时长必须靠它):跟 ffmpeg 同目录,ffmpeg 在 PATH 上时则用裸名
const probeName = FF.toLowerCase().endsWith(".exe") ? "ffprobe.exe" : "ffprobe";
const ffprobe = arg("ffprobe", FF.endsWith(probeName) ? FF : FF.replace(/ffmpeg(\.exe)?$/, "") + probeName);
const prFound = resolved(ffprobe);
ok("ffprobe", !!prFound, ffprobe, prFound ? "" : ffFound ? "和 ffmpeg 同目录,一般一起装" : "先装上 ffmpeg 再来看这条");
// 3) 中文字体
const fontFound = resolved(FONT);
ok("中文字体", !!fontFound, FONT, fontFound ? "" : "装个 SimHei,或用 --font 指到别的.ttf");
// 4) edge_tts:先把候选解释器都探一遍
const pys = [];
const extra = arg("py", "");
if (extra) pys.push(extra);
try {
  pys.push(execFileSync("where", ["python"], { encoding: "utf8" }).trim().split(/\r?\n/)[0]);
} catch {}
// WorkBuddy 托管 python 的几种可能位置(用 homedir,不写死某台机器)
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
ok("edge_tts", !!hit, hit || "所有候选 python 都没装 edge_tts",
  hit ? "" : "用装了包的那个 python: " +
  `<你的python>/pip install edge-tts —— 注意 PATH 里的 python3 不一定是它,` +
  "建议全程用绝对路径调用");
// 5) 页图
const pagesDir = arg("pages", "pages");
const pn = existsSync(join(JOB, pagesDir)) ? readdirSync(join(JOB, pagesDir)).filter((f) => /\.(png|jpg)$/i.test(f)).length : 0;
ok("页图", pn > 0, join(JOB, pagesDir), pn ? `${pn} 张` : "先跑抽页图(LibreOffice 转 PDF + pymupdf)");
// 6) 磁盘预算(只提示,不判定失败)
//    Node 在 Windows 上拿不到 free space,改成按成片码率估算:
//    1080p 30fps crf20 约 1.9 Mbps ≈ 时长(秒) × 0.22 MB
const mc = arg("minutes", "");
if (mc) {
  const est = parseFloat(mc) * 60 * 0.22;
  ok("磁盘预算", est < 5000, "预计成片", `${mc} 分钟 ≈ ${est.toFixed(0)} MB`);
}

const bad = rows.filter((r) => r[0] === "FAIL");
console.log("\n=== 环境自检 ===");
for (const [s, n, loc, tip] of rows) {
  console.log(`${s === "OK  " ? "✅" : "❌"} ${n.padEnd(10)} ${loc}${tip ? "\n    ↳ " + tip : ""}`);
}
console.log(`\n合计 ${rows.length} 项,不通过 ${bad.length} 项${bad.length ? " —— 先补齐再开工" : " —— 可以开工"}\n`);
if (bad.length) process.exit(2);
