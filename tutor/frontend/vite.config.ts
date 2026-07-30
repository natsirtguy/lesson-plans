import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        // Keep React in its own long-lived chunk. The lesson renderer is already
        // split out by the dynamic import in Markdown.tsx.
        manualChunks: { react: ["react", "react-dom", "react-router-dom"] },
      },
    },
  },
});
