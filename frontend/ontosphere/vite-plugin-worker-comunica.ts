import { build, type Plugin as EsbuildPlugin } from "esbuild";
import type { Plugin } from "vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const VIRTUAL_ID = "\0virtual:comunica-prebundled";
const DIAG_STUB_ID = "\0virtual:node-diagnostics-channel-stub";
const COMUNICA_PKG = "@comunica/query-sparql-rdfjs";

/**
 * esbuild plugin that stubs `node:diagnostics_channel` for the browser.
 *
 * lru-cache (used by Comunica) imports this Node.js built-in. Vite's default
 * browser-external Proxy stub returns undefined for all property accesses, so
 * `(0, L.channel)("lru-cache:metrics")` throws at module initialisation time.
 * This stub provides no-op implementations that satisfy lru-cache's usage.
 */
export const diagnosticsChannelStub: EsbuildPlugin = {
  name: "stub-node-diagnostics-channel",
  setup(build) {
    build.onResolve({ filter: /^node:diagnostics_channel$/ }, () => ({
      path: "node-diagnostics-channel-stub",
      namespace: "diagnostics-channel-stub",
    }));
    build.onLoad({ filter: /.*/, namespace: "diagnostics-channel-stub" }, () => ({
      contents: `
        const noop = () => {};
        const noopChannel = () => ({
          hasSubscribers: false,
          subscribe: noop,
          unsubscribe: noop,
          publish: () => false,
          bindStore: noop,
          unbindStore: noop,
        });
        module.exports = {
          channel: noopChannel,
          tracingChannel: noopChannel,
          hasSubscribers: () => false,
          subscribe: noop,
          unsubscribe: noop,
        };
      `,
      loader: "js",
    }));
  },
};

const DIAG_CHANNEL_ESM_STUB = `
const noop = () => {};
const noopChannel = () => ({
  hasSubscribers: false,
  subscribe: noop,
  unsubscribe: noop,
  publish: () => false,
  bindStore: noop,
  unbindStore: noop,
});
export const channel = noopChannel;
export const tracingChannel = noopChannel;
export const hasSubscribers = () => false;
export const subscribe = noop;
export const unsubscribe = noop;
export default { channel: noopChannel, tracingChannel: noopChannel, hasSubscribers: () => false, subscribe: noop, unsubscribe: noop };
`;

/**
 * Pre-bundles Comunica with esbuild when building the web worker.
 *
 * Vite's Rollup worker bundler generates broken require_libXXX stubs for
 * Comunica's circular CJS deps. esbuild handles them correctly (same as
 * InProcessWorker tests). This plugin intercepts the Comunica import inside
 * the worker bundle and substitutes an esbuild-compiled flat ESM module.
 */
export function workerComunicaPlugin(): Plugin {
  let prebundled: string | null = null;
  const __dirname = path.dirname(fileURLToPath(import.meta.url));

  return {
    name: "worker-comunica-prebundle",

    async buildStart() {
      if (prebundled) return;
      const result = await build({
        stdin: {
          contents: `export { QueryEngine } from "${COMUNICA_PKG}";`,
          resolveDir: __dirname,
          loader: "ts",
        },
        bundle: true,
        platform: "browser",
        format: "esm",
        target: "es2020",
        write: false,
        logLevel: "silent",
        define: {
          global: "globalThis",
        },
        plugins: [diagnosticsChannelStub],
      });
      prebundled = result.outputFiles[0].text;
    },

    enforce: "pre" as const,

    resolveId(id: string) {
      if (id === COMUNICA_PKG) return VIRTUAL_ID;
      if (id === "node:diagnostics_channel" || id === "diagnostics_channel")
        return DIAG_STUB_ID;
    },

    load(id: string) {
      if (id === VIRTUAL_ID) return prebundled ?? "";
      if (id === DIAG_STUB_ID) return DIAG_CHANNEL_ESM_STUB;
    },
  };
}
