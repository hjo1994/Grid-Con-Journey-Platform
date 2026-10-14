/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the backend runs on :8000; /api is proxied so no CORS is needed.
// Where /api is routed in production is a deployment decision (see README).
export default defineConfig({
  plugins: [react()],
  // Vite 8 minifies CSS with lightningcss, which rejects an ESNext CSS target.
  build: { target: "ESNext", cssTarget: "es2022", outDir: "build" },
  server: {
    // 5173 is the AI Cockpit frontend.
    port: 5174,
    proxy: { "/api": process.env.VITE_DEV_API_TARGET ?? "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
  },
});
