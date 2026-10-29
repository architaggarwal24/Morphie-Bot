/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

// The built app lands in ../public: Cloudflare serves it straight from the edge, and Flask serves the same
// files locally (see src/app.py). Everything under web/public (e.g. _headers) is copied there verbatim.
const API_ROUTES = ["/chat", "/status", "/providers", "/documents"];
const FLASK = process.env.MORPHIE_API ?? "http://127.0.0.1:5000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../public",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    // No inline <script> may ever reach index.html: the CSP is script-src 'self'.
    modulePreload: { polyfill: false },
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Long-lived vendor chunks: an app change doesn't make returning visitors re-download React or Motion.
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
          if (/[\\/](motion|framer-motion|motion-dom|motion-utils)[\\/]/.test(id)) return "motion";
          if (/[\\/]lucide-react[\\/]/.test(id)) return "icons";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    // `npm run dev` + `python src/app.py`: API calls go to Flask. changeOrigin keeps the CSRF Origin check happy.
    proxy: Object.fromEntries(API_ROUTES.map((r) => [r, { target: FLASK, changeOrigin: true, headers: { Origin: FLASK } }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
