import type { Config } from "tailwindcss"

const rgbVar = (name: string) => `rgb(var(${name}) / <alpha-value>)`

export const geistPreset = {
  darkMode: ["class"],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: rgbVar("--border"),
        input: rgbVar("--input"),
        ring: rgbVar("--ring"),
        background: rgbVar("--background"),
        foreground: rgbVar("--foreground"),
        primary: {
          DEFAULT: rgbVar("--primary"),
          foreground: rgbVar("--primary-foreground"),
        },
        secondary: {
          DEFAULT: rgbVar("--secondary"),
          foreground: rgbVar("--secondary-foreground"),
        },
        muted: {
          DEFAULT: rgbVar("--muted"),
          foreground: rgbVar("--muted-foreground"),
        },
        accent: {
          DEFAULT: rgbVar("--accent"),
          foreground: rgbVar("--accent-foreground"),
        },
        destructive: {
          DEFAULT: rgbVar("--destructive"),
          foreground: rgbVar("--destructive-foreground"),
        },
        card: {
          DEFAULT: rgbVar("--card"),
          foreground: rgbVar("--card-foreground"),
        },
        success: {
          DEFAULT: rgbVar("--success"),
          foreground: rgbVar("--success-foreground"),
        },
        warning: {
          DEFAULT: rgbVar("--warning"),
          foreground: rgbVar("--warning-foreground"),
        },
        info: {
          DEFAULT: rgbVar("--info"),
          foreground: rgbVar("--info-foreground"),
        },
        feature: {
          DEFAULT: rgbVar("--feature"),
          foreground: rgbVar("--feature-foreground"),
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)"],
        mono: ["var(--font-geist-mono)"],
      },
      borderRadius: {
        lg: "var(--radius-md)",
        md: "var(--radius-sm)",
        sm: "calc(var(--radius-sm) - 2px)",
        xl: "var(--radius-lg)",
        full: "var(--radius-full)",
      },
      boxShadow: {
        sm: "var(--shadow-raised)",
        md: "var(--shadow-popover)",
        lg: "var(--shadow-modal)",
        xl: "var(--shadow-modal)",
        "geist-raised": "var(--shadow-raised)",
        "geist-popover": "var(--shadow-popover)",
        "geist-modal": "var(--shadow-modal)",
      },
      transitionTimingFunction: {
        geist: "var(--ease-geist)",
      },
    },
  },
  plugins: [],
} satisfies Config
