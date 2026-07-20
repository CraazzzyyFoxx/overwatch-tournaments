import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: [
      "src/app/**/tournaments/**/draft/**/*.test.ts",
      "src/app/**/tournaments/**/veto/**/*.test.ts",
      "src/app/admin/tournaments/**/components/draft/**/*.test.ts",
      "src/app/admin/tournaments/**/components/mapVeto.helpers.test.ts",
      "src/app/**/users/compare/**/*.test.ts",
      "src/components/tournaments/**/*.test.ts",
    ],
  },
});
