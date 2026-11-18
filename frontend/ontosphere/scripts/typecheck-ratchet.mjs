#!/usr/bin/env node
// Typecheck ratchet: the project is built with esbuild/SWC (no type-checking),
// so a large backlog of pre-existing `tsc` errors exists. Demanding zero overnight
// is unrealistic; instead we ratchet — CI fails only if the error count INCREASES
// above the committed baseline. Drive the baseline down over time; never let it grow.
//
// Usage:
//   node scripts/typecheck-ratchet.mjs           # fail if errors > baseline
//   node scripts/typecheck-ratchet.mjs --update   # rewrite baseline to current count
//
// Baseline lives in .tsc-baseline.json at repo root.

import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const baselineFile = join(repoRoot, '.tsc-baseline.json');

function countErrors() {
  try {
    execSync('npx tsc --noEmit -p tsconfig.app.json', { cwd: repoRoot, stdio: 'pipe' });
    return 0; // tsc exited 0 → no errors
  } catch (err) {
    const out = `${err.stdout || ''}${err.stderr || ''}`;
    const matches = out.match(/error TS\d+/g);
    return matches ? matches.length : 0;
  }
}

const current = countErrors();
const update = process.argv.includes('--update');

if (update || !existsSync(baselineFile)) {
  writeFileSync(baselineFile, JSON.stringify({ maxErrors: current }, null, 2) + '\n');
  console.log(`[typecheck-ratchet] baseline written: ${current} errors`);
  process.exit(0);
}

const { maxErrors } = JSON.parse(readFileSync(baselineFile, 'utf8'));

if (current > maxErrors) {
  console.error(
    `[typecheck-ratchet] FAIL: ${current} tsc errors > baseline ${maxErrors}.\n` +
    `  You introduced new type errors. Fix them, or — only if intentional and justified — ` +
    `run \`node scripts/typecheck-ratchet.mjs --update\`.`,
  );
  process.exit(1);
}

if (current < maxErrors) {
  console.log(
    `[typecheck-ratchet] IMPROVED: ${current} < baseline ${maxErrors}. ` +
    `Please lower the baseline: \`node scripts/typecheck-ratchet.mjs --update\`.`,
  );
  // Improvement is not a failure; encourage ratcheting down but pass.
  process.exit(0);
}

console.log(`[typecheck-ratchet] OK: ${current} errors == baseline ${maxErrors}.`);
process.exit(0);
