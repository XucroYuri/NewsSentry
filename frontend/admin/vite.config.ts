import path from "node:path"

import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const defaultOutDir = "dist"
const outDir = process.env.FRONTEND_OUTPUT_SUBDIR
  ? path.resolve(process.env.FRONTEND_OUTPUT_SUBDIR, "admin")
  : defaultOutDir

export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@backend": path.resolve(__dirname, "../../backend/src/backend"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    assetsDir: "assets",
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
})
