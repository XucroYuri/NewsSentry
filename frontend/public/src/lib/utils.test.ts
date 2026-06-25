import { describe, expect, it } from "vitest"
import { cn } from "@/lib/utils"

describe("cn", () => {
  it("returns empty string for no arguments", () => {
    expect(cn()).toBe("")
  })

  it("joins multiple class strings with space", () => {
    expect(cn("text-red-500", "bg-blue-100")).toBe("text-red-500 bg-blue-100")
  })

  it("filters out falsy values", () => {
    expect(cn("font-bold", false && "hidden", undefined, null, 0 && "opacity-0")).toBe(
      "font-bold",
    )
  })

  it("resolves tailwind conflicts via twMerge (later wins)", () => {
    // bg-blue-100 overwrites bg-red-500 due to twMerge
    const result = cn("bg-red-500", "bg-blue-100")
    expect(result).toBe("bg-blue-100")
  })

  it("handles conditional class object", () => {
    const result = cn("base", { "text-lg": true, "text-sm": false })
    expect(result).toBe("base text-lg")
  })
})
