import { readFileSync } from "node:fs"
import path from "node:path"

import react from "@vitejs/plugin-react"
import type { Plugin } from "vite"
import { defineConfig } from "vitest/config"

const isCloudflarePages = process.env.FRONTEND_OUTPUT_SUBDIR === undefined
const defaultOutDir = isCloudflarePages ? "dist" : path.resolve(process.env.FRONTEND_OUTPUT_SUBDIR!, "public_app")
const base = isCloudflarePages ? "/" : "/public-app/"
const defaultApiBase = "https://api.news-sentry.com"

function resolveApiBase(): string {
  const raw = (process.env.VITE_API_BASE ?? defaultApiBase).trim()
  const parsed = new URL(raw)
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`Unsupported VITE_API_BASE protocol: ${parsed.protocol}`)
  }
  const localHttpHosts = new Set(["localhost", "127.0.0.1", "[::1]"])
  if (parsed.protocol === "http:" && !localHttpHosts.has(parsed.hostname)) {
    throw new Error("VITE_API_BASE must use HTTPS outside local development")
  }
  if (parsed.pathname !== "/" || parsed.search || parsed.hash || parsed.username || parsed.password) {
    throw new Error("VITE_API_BASE must be an HTTP(S) origin without credentials, path, query, or hash")
  }
  return parsed.origin
}

function newsSentryPagesMetadata(): Plugin {
  const apiBase = resolveApiBase()
  const headersTemplate = readFileSync(
    path.resolve(__dirname, "cloudflare-pages.headers"),
    "utf8",
  )

  return {
    name: "news-sentry-pages-metadata",
    transformIndexHtml(html) {
      return html.split("__NEWS_SENTRY_API_BASE__").join(apiBase)
    },
    generateBundle() {
      if (!isCloudflarePages) return
      this.emitFile({
        type: "asset",
        fileName: "_headers",
        source: headersTemplate.split("__NEWS_SENTRY_API_ORIGIN__").join(apiBase),
      })
    },
  }
}

export default defineConfig({
  base,
  plugins: [react(), newsSentryPagesMetadata()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    fs: {
      allow: [path.resolve(__dirname, "..")],
    },
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
