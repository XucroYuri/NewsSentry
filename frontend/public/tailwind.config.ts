import type { Config } from "tailwindcss"

import { geistPreset } from "../design-system/tailwind-geist-preset"

export default {
  presets: [geistPreset],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
} satisfies Config
