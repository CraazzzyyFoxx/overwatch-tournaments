import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // `react-resizable-panels` conditionally exports a stripped-down
      // "edge-light" build under the `node` condition (no layout effects — it
      // targets edge runtimes without a DOM). Node's own module resolution
      // picks that condition once the package is externalized/required by
      // Vitest, even under `@vitest-environment happy-dom`, so every
      // imperative call (`collapse()`/`resize()`) throws "Panel size not
      // found". Alias straight to the real browser build, matching what
      // Next.js's client bundler resolves in production.
      "react-resizable-panels": fileURLToPath(
        new URL(
          "./node_modules/react-resizable-panels/dist/react-resizable-panels.browser.development.js",
          import.meta.url
        )
      )
    },
    dedupe: ["react", "react-dom"]
  },
  test: {
    // Externalized deps are loaded by Node and resolve their own CJS `react`,
    // whose hook dispatcher react-dom never sets. `@tanstack/react-table` calls
    // hooks, so every `useReactTable` render threw "Invalid hook call" until it
    // was inlined through Vite alongside the app code. `cmdk` calls `useRef` the
    // same way, so every combobox popover threw the moment it opened.
    server: { deps: { inline: ["@tanstack/react-table", "cmdk"] } },
    environment: "node",
    // A plain glob, not an allow-list. The frontend used to run two runners
    // (vitest plus `bun test` on the complement), which forced a hand-kept
    // file-level `include` — and an unmatched file is silently not collected,
    // so nine tests once sat green without ever running. One runner, one glob:
    // every `*.test.ts(x)` under `src` is collected by construction.
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"]
  }
});
