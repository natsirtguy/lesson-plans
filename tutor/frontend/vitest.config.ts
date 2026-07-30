import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // KaTeX and highlight.js ship CSS that Vite would try to process; the tests
    // exercise logic, not styling.
    css: false,
  },
});
