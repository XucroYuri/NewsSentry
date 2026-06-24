import path from "node:path"

import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const defaultOutDir = "../../src/news_sentry/static/admin"
const outDir = process.env.FRONTEND_OUTPUT_SUBDIR
  ? path.resolve(process.env.FRONTEND_OUTPUT_SUBDIR, "admin")
  : defaultOutDir

export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    assetsDir: "assets",
  },
  test: {
    environment: "jsdom",
  },
})
