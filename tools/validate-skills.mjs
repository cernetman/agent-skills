#!/usr/bin/env node
/**
 * Validate the YAML frontmatter of skills/<name>/SKILL.md.
 *
 * Checks:
 *   1. SKILL.md exists under skills/<name>/
 *   2. A YAML frontmatter block is present
 *   3. The frontmatter name matches the directory name and follows the [a-z0-9-] naming rule
 *   4. description is present, non-empty, and no longer than 1024 characters
 *   5. If version is declared, it looks like x.y.z
 *
 * Usage: node tools/validate-skills.mjs
 * Exit codes: 0 all passed / 1 at least one failure
 */
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const skillsDir = join(repoRoot, "skills");

const NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
const MAX_DESCRIPTION = 1024;

/** Parses only top-level "key: value" scalars; good enough, with no third-party dependency. */
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
    console.error("[x] skills/ directory not found");
    return 1;
  }

  const dirs = readdirSync(skillsDir).filter((d) => statSync(join(skillsDir, d)).isDirectory());
  if (dirs.length === 0) {
    console.error("[x] no skill directories under skills/");
    return 1;
  }

  const failures = [];
  for (const dir of dirs.sort()) {
    const file = join(skillsDir, dir, "SKILL.md");
    if (!existsSync(file)) {
      failures.push(`${dir}: missing SKILL.md`);
      continue;
    }

    const fields = parseFrontmatter(readFileSync(file, "utf8"));
    if (!fields) {
      failures.push(`${dir}: no YAML frontmatter`);
      continue;
    }

    const problems = [];
    if (!fields.name) problems.push('missing "name"');
    else if (fields.name !== dir) problems.push(`name "${fields.name}" does not match directory name "${dir}"`);
    else if (!NAME_RE.test(fields.name)) problems.push(`name "${fields.name}" does not follow the [a-z0-9-] naming rule`);

    if (!fields.description) problems.push('missing "description"');
    else if (fields.description.length > MAX_DESCRIPTION) {
      problems.push(`description length ${fields.description.length} > ${MAX_DESCRIPTION}`);
    }

    if (fields.version && !SEMVER_RE.test(fields.version)) {
      problems.push(`version "${fields.version}" is not x.y.z`);
    }

    if (problems.length > 0) failures.push(`${dir}: ${problems.join("; ")}`);
    else console.log(`OK   ${dir}  (v${fields.version ?? "?"})`);
  }

  if (failures.length > 0) {
    console.error(`\n[x] ${failures.length} skill(s) failed validation:`);
    for (const f of failures) console.error("   -", f);
    return 1;
  }
  console.log(`\n[√] all ${dirs.length} skills passed validation`);
  return 0;
}

process.exit(main());
