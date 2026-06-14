import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA is served by Django:
//  - assets are emitted under /static/ so Django's staticfiles serves them
//  - the build is written to ../frontend_dist, which Django registers as a
//    static + template directory
// During local development, `npm run dev` runs Vite on :5173 and proxies API
// calls to the Django server on :8000.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../frontend_dist",
    emptyOutDir: true,
    manifest: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
