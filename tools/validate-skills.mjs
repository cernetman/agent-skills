#!/usr/bin/env node
/**
 * 校验 skills/<name>/SKILL.md 的 YAML frontmatter 是否合法。
 *
 * 检查项:
 *   1. skills/<name>/ 下存在 SKILL.md
 *   2. 有 YAML frontmatter 块
 *   3. frontmatter 的 name 与目录名一致，且符合 [a-z0-9-] 命名
 *   4. 有非空 description，且不超过 1024 字符
 *   5. 若声明了 version，需形如 x.y.z
 *
 * 用法: node tools/validate-skills.mjs
 * 退出码: 0 全部通过 / 1 有失败项
 */
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const skillsDir = join(repoRoot, "skills");

const NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
const MAX_DESCRIPTION = 1024;

/** 只解析顶层 "key: value" 标量，够用且不引第三方依赖。 */
function parseFrontmatter(text) {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!m) return null;
  const fields = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (kv) fields[kv[1]] = kv[2].trim().replace(/^["']|["']$/g, "");
  }
  return fields;
}

function main() {
  if (!existsSync(skillsDir)) {
    console.error("[x] 找不到 skills/ 目录");
    return 1;
  }

  const dirs = readdirSync(skillsDir).filter((d) => statSync(join(skillsDir, d)).isDirectory());
  if (dirs.length === 0) {
    console.error("[x] skills/ 下没有任何技能目录");
    return 1;
  }

  const failures = [];
  for (const dir of dirs.sort()) {
    const file = join(skillsDir, dir, "SKILL.md");
    if (!existsSync(file)) {
      failures.push(`${dir}: 缺少 SKILL.md`);
      continue;
    }

    const fields = parseFrontmatter(readFileSync(file, "utf8"));
    if (!fields) {
      failures.push(`${dir}: 没有 YAML frontmatter`);
      continue;
    }

    const problems = [];
    if (!fields.name) problems.push('缺少 "name"');
    else if (fields.name !== dir) problems.push(`name "${fields.name}" 与目录名 "${dir}" 不一致`);
    else if (!NAME_RE.test(fields.name)) problems.push(`name "${fields.name}" 不符合 [a-z0-9-] 命名`);

    if (!fields.description) problems.push('缺少 "description"');
    else if (fields.description.length > MAX_DESCRIPTION) {
      problems.push(`description 长度 ${fields.description.length} > ${MAX_DESCRIPTION}`);
    }

    if (fields.version && !SEMVER_RE.test(fields.version)) {
      problems.push(`version "${fields.version}" 不是 x.y.z`);
    }

    if (problems.length > 0) failures.push(`${dir}: ${problems.join("; ")}`);
    else console.log(`OK   ${dir}  (v${fields.version ?? "?"})`);
  }

  if (failures.length > 0) {
    console.error(`\n[x] ${failures.length} 个技能未通过校验：`);
    for (const f of failures) console.error("   -", f);
    return 1;
  }
  console.log(`\n[√] ${dirs.length} 个技能全部通过校验`);
  return 0;
}

process.exit(main());
