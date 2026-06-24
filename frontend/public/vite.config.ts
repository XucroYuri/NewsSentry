import path from "node:path"

import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const defaultOutDir = "../../src/news_sentry/static/public_app"
const outDir = process.env.FRONTEND_OUTPUT_SUBDIR
  ? path.resolve(process.env.FRONTEND_OUTPUT_SUBDIR, "public_app")
  : defaultOutDir

export default defineConfig({
  base: "/public-app/",
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
