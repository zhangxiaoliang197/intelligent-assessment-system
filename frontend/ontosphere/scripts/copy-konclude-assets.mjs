#!/usr/bin/env node
// Copies Konclude WASM assets from node_modules to public/ so the Vite dev
// server and production build can serve them at the absolute public URL used
// by the inline KoncludeReasoner worker spawn.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const src = resolve(root, "node_modules/rdf-reasoner-konclude/dist");
const dest = resolve(root, "public/rdf-reasoner-konclude");

mkdirSync(dest, { recursive: true });

const assets = ["worker.js", "konclude.mjs", "konclude.wasm"];
for (const file of assets) {
  copyFileSync(resolve(src, file), resolve(dest, file));
  console.log(`copied: ${file}  →  public/rdf-reasoner-konclude/${file}`);
}

// Copy coi-serviceworker for SharedArrayBuffer support on static hosts (GitHub Pages).
// Patch: skip COOP/COEP headers for relay.html so window.opener is not severed
// when the relay popup is opened from a cross-origin AI chat tab.
const coiSrc = resolve(root, "node_modules/coi-serviceworker/coi-serviceworker.js");
const coiDest = resolve(root, "public/coi-serviceworker.js");
copyFileSync(coiSrc, coiDest);
let coiContent = readFileSync(coiDest, "utf8");
const RELAY_EXEMPTION = `
        // Relay popup needs window.opener — skip isolation headers so the
        // postMessage bridge to the AI chat tab is not severed by COOP.
        if (new URL(r.url).pathname.endsWith("/relay.html")) return;
`;
coiContent = coiContent.replace(
  'if (r.cache === "only-if-cached" && r.mode !== "same-origin") {\n            return;\n        }',
  'if (r.cache === "only-if-cached" && r.mode !== "same-origin") {\n            return;\n        }' + RELAY_EXEMPTION,
);
writeFileSync(coiDest, coiContent);
console.log("copied: coi-serviceworker.js  →  public/coi-serviceworker.js (patched for relay exemption)");
