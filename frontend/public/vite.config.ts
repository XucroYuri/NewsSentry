import path from "node:path"

import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const isCloudflarePages = process.env.FRONTEND_OUTPUT_SUBDIR === undefined
const defaultOutDir = isCloudflarePages ? "dist" : path.resolve(process.env.FRONTEND_OUTPUT_SUBDIR!, "public_app")
const base = isCloudflarePages ? "/" : "/public-app/"

export default defineConfig({
  base,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:50900",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: defaultOutDir,
    emptyOutDir: true,
    assetsDir: "assets",
  },
  test: {
    environment: "jsdom",
  },
})
