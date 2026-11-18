#!/usr/bin/env node
// Drift check: regenerate mcp.json content in-memory from src/mcp/manifest.ts
// and compare against public/.well-known/mcp.json.
// Exits 0 when in sync, non-zero (with explanation) when they differ.
// Run: node scripts/check-mcp-json.mjs
// Called by: npm run check:mcp  (CI / pre-push gate)
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
import { writeFileSync, unlinkSync } from 'fs';
import { transform } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// --- 1. Transpile and load manifest.ts in memory ---
const src = readFileSync(resolve(root, 'src/mcp/manifest.ts'), 'utf8');
const { code } = await transform(src, { loader: 'ts', format: 'esm', target: 'node18' });

const tmp = resolve(root, 'scripts/_manifest_check_tmp.mjs');
writeFileSync(tmp, code);

let manifest, serverName, serverDescription;
try {
  const mod = await import(pathToFileURL(tmp).href + '?t=' + Date.now());
  manifest = mod.mcpManifest;
  serverName = mod.mcpServerName;
  serverDescription = mod.mcpServerDescription;
} finally {
  try { unlinkSync(tmp); } catch {}
}

// --- 2. Build the expected JSON (same shape as the generator) ---
const expected = JSON.stringify({ name: serverName, description: serverDescription, tools: manifest }, null, 2) + '\n';

// --- 3. Read the committed file ---
const dest = resolve(root, 'public/.well-known/mcp.json');
let actual;
try {
  actual = readFileSync(dest, 'utf8');
} catch {
  console.error(`ERROR: ${dest} does not exist. Run: npm run generate:mcp`);
  process.exit(1);
}

// --- 4. Compare ---
if (expected === actual) {
  const toolCount = manifest.length;
  console.log(`OK: public/.well-known/mcp.json is in sync with src/mcp/manifest.ts (${toolCount} tools).`);
  process.exit(0);
} else {
  // Produce a helpful diff: report which tool names differ
  let expectedObj, actualObj;
  try {
    expectedObj = JSON.parse(expected);
    actualObj = JSON.parse(actual);
  } catch {
    console.error('ERROR: JSON parse failed while diffing. Run: npm run generate:mcp');
    process.exit(1);
  }

  const expectedNames = new Set(expectedObj.tools.map(t => t.name));
  const actualNames = new Set(actualObj.tools.map(t => t.name));

  const added = [...expectedNames].filter(n => !actualNames.has(n));
  const removed = [...actualNames].filter(n => !expectedNames.has(n));

  console.error('ERROR: public/.well-known/mcp.json is OUT OF SYNC with src/mcp/manifest.ts.');
  if (added.length) console.error(`  Tools in manifest but missing from mcp.json: ${added.join(', ')}`);
  if (removed.length) console.error(`  Tools in mcp.json but missing from manifest: ${removed.join(', ')}`);
  if (!added.length && !removed.length) {
    console.error('  Tool list matches but content differs (description or inputSchema changed).');
    console.error(`  Expected ${expectedObj.tools.length} tools, found ${actualObj.tools.length} in file.`);
  }
  console.error('  Fix: npm run generate:mcp');
  process.exit(1);
}
