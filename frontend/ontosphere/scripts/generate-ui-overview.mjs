#!/usr/bin/env node
// scripts/generate-ui-overview.mjs
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const BASE = process.env.BASE_URL || 'http://localhost:8080';
const WIDTH = 1920;
const HEIGHT = 1080;

// ── Element measurement ──────────────────────────────────────────────
//
// Each entry: [markerNumber, humanLabel, selectorStrategy]
// selectorStrategy is a function receiving `document` inside page.evaluate
// and returning an Element or null.
//
// Selectors use titles, aria-labels, and text content — resilient to
// class-name churn.

const ELEMENT_MAP = [
  // Top bar — left
  [1,  'Menu',          () => document.querySelector('button[title="Menu"]')],
  [2,  'Search',        () => document.querySelector('input[placeholder*="earch"]')],

  // Top bar — right
  [3,  'Layout',        () => document.querySelector('button[title="Layout settings"]')],
  [4,  'ClusterAlgo',   () => document.querySelector('select') ||
                              [...document.querySelectorAll('button')].find(b =>
                                b.textContent.includes('Label Propagation') ||
                                b.textContent.includes('Louvain'))],
  [5,  'FoldLevel',     () => [...document.querySelectorAll('button')].find(b =>
                                /^\d+\/\d+$/.test(b.textContent.trim()))],
  [6,  'ABox',          () => document.querySelector('button[title*="A-Box"]')],
  [7,  'TBox',          () => document.querySelector('button[title*="T-Box"]')],
  [8,  'Ontologies',    () => document.querySelector('button[title="Loaded ontologies"]')],
  [9,  'Reasoning',     () => document.querySelector('button[title="View reasoning results"]')],
  [10, 'ClearInferred', () => document.querySelector('button[title="Clear inferred graph"]')],
  [11, 'SHACLToggle',   () => document.querySelector('button[title*="SHACL validation"]')],
  [12, 'RunReasoning',  () => document.querySelector('button[title="Run reasoning"]')],

  // Left sidebar — collapsed icon rail (top to bottom)
  [13, 'Onto',          () => document.querySelector('button[aria-label="Load Ontology"]')],
  [14, 'File',          () => document.querySelector('button[aria-label="Load File"]')],
  [15, 'Clear',         () => document.querySelector('button[aria-label="Clear Data"]')],
  [16, 'Export',        () => document.querySelector('button[aria-label="Export"]')],
  [17, 'SHACL',         () => document.querySelector('button[aria-label="SHACL Shapes"]')],
  [18, 'AgentEdits',    () => document.querySelector('button[aria-label="Agent Edits"]')],
  [19, 'SPARQL',        () => document.querySelector('button[aria-label="SPARQL Query"]')],
  [20, 'Metrics',       () => document.querySelector('button[aria-label="Ontology Metrics"]')],
  [21, 'Relay',         () => document.querySelector('button[aria-label="AI Relay"]')],
  [22, 'ZoomControls',  () => {
                              const btns = [...document.querySelectorAll('button')].filter(b => {
                                const r = b.getBoundingClientRect();
                                return r.x > 40 && r.x < 110 && r.y > 300 && r.y < 700;
                              });
                              if (!btns.length) return null;
                              const first = btns[0].getBoundingClientRect();
                              const last = btns[btns.length - 1].getBoundingClientRect();
                              return { _synthetic: true,
                                x: first.x, y: first.y,
                                width: Math.max(first.width, last.width),
                                height: last.y + last.height - first.y };
                            }],
  [23, 'Docs',          () => document.querySelector('button[aria-label="Documentation"]')],
  [24, 'Settings',      () => document.querySelector('button[aria-label="Settings"]')],

  // Bottom bar
  [25, 'Undo',          () => document.querySelector('button[title*="Undo"]')],
  [26, 'Redo',          () => document.querySelector('button[title*="Redo"]')],
  [27, 'Save',          () => [...document.querySelectorAll('button')].find(b =>
                                b.getBoundingClientRect().y > 900 && b.textContent.includes('Save'))],
  [28, 'Relayout',      () => [...document.querySelectorAll('button')].find(b =>
                                b.getBoundingClientRect().y > 900 && b.textContent.includes('Layout'))],

  // Canvas elements (pick first visible of each kind)
  [29, 'Node',          () => document.querySelector('.reactodia-paper [data-element-id]')],
  [30, 'Edge',          () => document.querySelector('.reactodia-paper [data-link-id]')],
  [31, 'Minimap',       () => document.querySelector('.reactodia-navigator')],
];

async function measureElements(page) {
  // Serialize the selector functions as strings so they survive page.evaluate
  const specs = ELEMENT_MAP.map(([num, label, selectorFn]) => [num, label, selectorFn.toString()]);

  return page.evaluate((specs) => {
    const results = {};
    for (const [num, label, fnSrc] of specs) {
      const fn = new Function('return (' + fnSrc + ')();');
      const elOrRect = fn();
      if (!elOrRect) { results[num] = null; continue; }

      let rect;
      if (elOrRect._synthetic) {
        rect = elOrRect;           // ZoomControls returns a plain object
      } else if (elOrRect.getBoundingClientRect) {
        rect = elOrRect.getBoundingClientRect();
      } else {
        results[num] = null; continue;
      }

      results[num] = {
        label,
        cx: Math.round(rect.x + rect.width / 2),
        cy: Math.round(rect.y + rect.height / 2),
        top: Math.round(rect.y),
        bottom: Math.round(rect.y + rect.height),
        left: Math.round(rect.x),
        right: Math.round(rect.x + rect.width),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      };
    }
    return results;
  }, specs);
}

// ── SVG builder ──────────────────────────────────────────────────────

function buildSvg(b64png, width, height, positions) {
  const R = 12; // marker circle radius

  const markers = [];
  for (const [numStr, pos] of Object.entries(positions)) {
    if (!pos) continue;
    const num = Number(numStr);
    const { cx, cy, top, bottom, left, right, label } = pos;

    // Decide marker offset direction based on element location
    let mx, my, lx, ly;
    if (top < 60) {
      // Top bar → marker below toolbar
      mx = cx; my = bottom + R + 4;
      lx = cx; ly = bottom;
    } else if (left < 50) {
      // Sidebar → marker to the right
      mx = right + R + 4; my = cy;
      lx = right; ly = cy;
    } else if (top > height - 80) {
      // Bottom bar → marker above
      mx = cx; my = top - R - 4;
      lx = cx; ly = top;
    } else if (label === 'Minimap') {
      // Minimap → marker to the left
      mx = left - R - 4; my = cy;
      lx = left; ly = cy;
    } else if (label === 'ZoomControls') {
      // Zoom → marker to the right
      mx = right + R + 4; my = cy;
      lx = right; ly = cy;
    } else {
      // Canvas elements → marker above
      mx = cx; my = top - R - 4;
      lx = cx; ly = top;
    }

    // Clamp within image bounds
    mx = Math.max(R + 1, Math.min(width - R - 1, mx));
    my = Math.max(R + 1, Math.min(height - R - 1, my));

    const fontSize = num < 10 ? 13 : 10;
    markers.push(`
  <!-- ${num}: ${label} -->
  <line class="ln" x1="${mx}" y1="${my + (ly > my ? R : -R)}" x2="${lx}" y2="${ly}"/>
  <circle class="cl" cx="${mx}" cy="${my}" r="${R}" filter="url(#ds)"/>
  <text class="ct" style="font-size:${fontSize}px" x="${mx}" y="${my}">${num}</text>`);
  }

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <style>
      .cl { fill: #F59E0B; stroke: rgba(0,0,0,0.75); stroke-width: 1.5; }
      .ct { fill: #000; font-family: Arial, Helvetica, sans-serif; font-weight: bold;
            dominant-baseline: central; text-anchor: middle; }
      .ln { stroke: #F59E0B; stroke-width: 1.5; opacity: 0.9; }
    </style>
    <filter id="ds">
      <feDropShadow dx="0" dy="0" stdDeviation="2" flood-color="rgba(0,0,0,0.9)" flood-opacity="1"/>
    </filter>
  </defs>

  <image href="data:image/png;base64,${b64png}" width="${width}" height="${height}"/>
${markers.join('\n')}
</svg>`;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    colorScheme: 'dark',
  });
  const page = await context.newPage();

  // Force dark theme before any page load
  await page.addInitScript(() => {
    localStorage.setItem('ontosphere-theme', 'dark');
  });

  // Navigate and wait for data to load
  const url = `${BASE}/?rdfUrl=${encodeURIComponent(BASE + '/reasoning-demo.ttl')}`;
  console.log(`Navigating to ${url}`);
  await page.goto(url, { waitUntil: 'networkidle' });

  // Wait for canvas nodes to appear (reasoning-demo has 8 entities)
  await page.waitForFunction(
    () => document.querySelectorAll('.reactodia-paper [data-element-id]').length >= 6,
    { timeout: 15000 },
  );

  // Switch to ABox view and wait for it to activate
  const aboxBtn = page.locator('button[title="View instance data (A-Box)"]');
  if (!(await aboxBtn.evaluate(el => el.classList.contains('glass-btn--active')))) {
    await aboxBtn.click();
    await page.waitForTimeout(1500);
  }

  // Let layout and animations settle
  await page.waitForTimeout(2000);

  // ── Step A: Screenshot ──
  const pngPath = resolve(ROOT, 'public/ui-overview.png');
  await page.screenshot({ path: pngPath, type: 'png' });
  console.log(`Screenshot saved: ${pngPath}`);

  // ── Step B: Measure all UI element positions ──
  const positions = await measureElements(page);
  console.log(`Measured ${Object.keys(positions).length} elements`);

  // ── Step C: Build SVG ──
  const pngBuf = readFileSync(pngPath);
  const b64 = pngBuf.toString('base64');
  const svg = buildSvg(b64, WIDTH, HEIGHT, positions);
  const svgPath = resolve(ROOT, 'public/ui-overview.svg');
  writeFileSync(svgPath, svg);
  console.log(`SVG saved: ${svgPath} (${(svg.length / 1024).toFixed(0)} KB)`);

  await browser.close();
}

main().catch(err => { console.error(err); process.exit(1); });
