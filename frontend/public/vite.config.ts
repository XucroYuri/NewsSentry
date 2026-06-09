import path from "node:path"

import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

export default defineConfig({
  base: "/public-app/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "../../src/news_sentry/static/public_app",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  test: {
    environment: "jsdom",
  },
})
