# News Sentry Geist Frontend Guidelines

News Sentry uses Vercel's Geist design system as the shared frontend baseline for
the public reader and admin console. The source references are stored under
`docs/design/vendor/vercel/`; this file defines the News Sentry mapping.

## Design Intent

- Public reader: a fast, scan-friendly news intelligence surface. Prioritize
  hierarchy, reading context, filter clarity, and compact story density.
- Admin console: a dense operational tool. Keep tables, controls, diagnostics,
  and state markers quiet and legible; avoid marketing-style sections.
- Both frontends share tokens, fonts, focus behavior, radii, shadows, and status
  color semantics.

## Token Mapping

- Use `frontend/design-system/geist-tokens.css` as the CSS variable source.
- Use `frontend/design-system/tailwind-geist-preset.ts` as the Tailwind source.
- Semantic Tailwind colors remain stable: `background`, `foreground`, `card`,
  `primary`, `secondary`, `muted`, `accent`, `destructive`, `border`, `input`,
  and `ring`.
- Status color semantics:
  - `success`: healthy, ready, positive, completed.
  - `warning`: degraded, missing data, attention needed.
  - `info`: links, neutral source/entity identity, informational markers.
  - `feature`: categorical/entity distinction when status is not implied.
  - `destructive`: errors, failed, unauthorized, destructive actions.

## Component Rules

- Buttons use 6px radius (`rounded-md`), 40px default height, 32px compact height,
  and the Geist focus ring from `ring`.
- Cards and grouped panels use neutral surfaces, 12px radius, subtle borders, and
  minimal shadows. Do not nest decorative cards.
- Inputs use neutral surfaces, 6px radius, visible border, and 40px default height.
- Badges/chips are compact and semantic. Do not encode meaning with color alone;
  pair status color with text or an icon where the state matters.
- Tables use muted headers, neutral row hover, and status markers from semantic
  tokens rather than raw Tailwind color families.

## Theme Rules

- The default theme follows the system preference.
- `.light` and `.dark` classes on `:root` remain the explicit overrides.
- Both public and admin import the same token file; do not duplicate theme values
  inside each app.
- Fonts are local Geist Sans and Geist Mono. Remote font requests are not allowed
  for the reader or admin console.

## Change Discipline

- Do not modify public API shapes, route URLs, Cloudflare Worker contracts, or D1
  schema for visual work.
- Prefer shared primitives and semantic token usage over one-off color classes.
- Before merging visual changes, run the relevant frontend tests, builds, and a
  desktop/mobile visual QA pass in light and dark themes.
