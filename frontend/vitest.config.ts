import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    },
    dedupe: ["react", "react-dom"]
  },
  test: {
    // Externalized deps are loaded by Node and resolve their own CJS `react`,
    // whose hook dispatcher react-dom never sets. `@tanstack/react-table` calls
    // hooks, so every `useReactTable` render threw "Invalid hook call" until it
    // was inlined through Vite alongside the app code. `cmdk` calls `useRef` the
    // same way, so every combobox popover threw the moment it opened. The admin kit's
    // ESM imports `next/navigation` and `next/link`, which Node cannot resolve itself;
    // `@uiw/*` ESM imports `.css` files, which only Vite can load.
    server: {
      deps: { inline: ["@tanstack/react-table", "cmdk", "@craazzzyyfoxx/admin-kit", /@uiw\//] }
    },
    environment: "node",
    // Node 25+ ships a global `localStorage` stub (no methods without
    // `--localstorage-file`) that shadows happy-dom's, so every
    // `localStorage.getItem` threw.
    execArgv: ["--no-experimental-webstorage"],
    // A plain glob, not an allow-list. The frontend used to run two runners
    // (vitest plus `bun test` on the complement), which forced a hand-kept
    // file-level `include` — and an unmatched file is silently not collected,
    // so nine tests once sat green without ever running. One runner, one glob:
    // every `*.test.ts(x)` under `src` is collected by construction.
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/test/setup.ts"]
  }
});
