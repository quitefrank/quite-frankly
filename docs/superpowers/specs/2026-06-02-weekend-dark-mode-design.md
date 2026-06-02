# Weekend editions: light/dark themes

**Date:** 2026-06-02
**Status:** Approved (design)
**Scope:** Colour only. No content, layout, copy, feed, or routing-logic changes.

## Goal

Give the newsletter two distinct, mutually inverse colour themes chosen by the
edition's day:

- **Weekday editions (Mon–Fri)** render **light** — byte-for-byte identical to
  today's output.
- **Weekend editions (Sat–Sun)** render **dark** — the inverse palette.

The theme is fixed in the HTML at send time and is the same on every device.
The weekend dark build also discourages email clients from applying their own
auto-inversion, which is what currently makes the light newsletter look
inconsistent between Frank's light desktop inbox and his dark-mode phone.

## Why not "follow the reader's system theme"

Email cannot run per-reader logic. The only system-theme hook is
`prefers-color-scheme`, which lets an email *match* the system (not invert
against it) and is ignored or overridden by major clients (Gmail web/app force
their own inversion). Inverting *opposite* to the reader's system is not
achievable. The day-based, baked-in model is the reliable realization of "two
distinct themes, inverse of each other."

## Trigger & data flow

No new routing. `routing.is_design_mode(mode)` is already `True` for
`SATURDAY_STRATEGIC` and `SUNDAY_VISUAL` and is already threaded into
`formatting.build_email_html(...)` as `is_design_edition` (set in
`newsletter.py`). The renderer derives `dark = is_design_edition` and selects a
palette from it. Weekday/Monday editions → light.

## Approach: palette object threaded through renderers

Two module-level dicts in `formatting.py`, `LIGHT` and `DARK`, keyed by semantic
role. Each hardcoded hex in the render functions is replaced with a palette
lookup, and a `palette` argument is threaded down the existing call chain.
`LIGHT` holds the exact current values, so weekday output cannot drift.

Functions that take a `palette` argument (the chain that already carries
`is_design_edition`):

- `render_source_line`
- `_render_body_markdown`
- `render_other_headlines_for_section`
- `_render_today_in_the_world`
- `parse_and_render_sections`
- `build_everything_else`
- `build_email_html` (selects `DARK if is_design_edition else LIGHT`, passes down)

Rejected alternatives:

- **Post-render hex find/replace** — fragile; `#fff`/`#1a1a1a` play several
  roles and the header bar inverts opposite to everything else, so a blanket
  swap breaks it.
- **`prefers-color-scheme` CSS** — see "Why not follow the reader's system."

## Palette

| Role (key) | LIGHT (current) | DARK (weekend) |
|---|---|---|
| `page_bg` | `#f4f4f4` | `#121212` |
| `header_bg` | `#1f1f1f` | `#ffffff` |
| `header_text` | `#fff` | `#1a1a1a` |
| `header_border` | `#222` | `#e6e6e6` |
| `card_bg` | `#ffffff` | `#1e1e1e` |
| `card_border` | `#e6e6e6` | `#2a2a2a` |
| `section_border` | *(none)* | `1px solid #2a2a2a` |
| `heading` | `#1a1a1a` | `#f5f5f5` |
| `body` | `#333` | `#c8c8c8` |
| `meta` | `#999` | `#7f7f7f` |
| `meta_label` | `#888` | `#8a8a8a` |
| `accent` | `#1c7ff2` | `#4d9bff` |
| `callout_bg` | `#f0f4ff` | `#16243a` |
| `panel_bg` (Everything Else + footer) | `#E9EBF7` | `#1a1c2e` |
| `footer_text` | `#79787d` | `#8b8ba3` |

Notes:

- The header bar is the one element already dark in light mode; in dark mode it
  inverts to a white bar with a dark logo + text (explicitly chosen by Frank).
  White-on-white would be invisible, so header text is dark in the dark theme.
- Callout text and link text reuse `body`/`heading` rather than new keys.
- `section_border` is empty in light (section cards and the footer/Everything
  Else panel are borderless today) and a hairline in dark for separation
  against the near-black page. This keeps light output identical.
- Accent blue brightens `#1c7ff2 → #4d9bff` on dark for legibility against the
  dark cards (approved trade-off; light keeps the exact brand blue).

## Anti-inversion hints (dark build only)

Add to the `<head>` of the weekend build:

```html
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
```

and `color-scheme: dark` on the `<body>` style. The light build keeps the
`light` equivalents. This tells well-behaved clients the email is already
themed and reduces (does not guarantee — Gmail may still override) client-side
re-inversion.

## Testing

In `tests/test_formatting.py`:

1. **Light regression guard** — `build_email_html(..., is_design_edition=False)`
   contains `#f4f4f4` and `#ffffff` and none of the dark markers
   (`#121212`, `#4d9bff`).
2. **Dark build** — `build_email_html(..., is_design_edition=True)` contains
   `#121212`, the white header background, `#4d9bff`, and
   `color-scheme` / `content="dark"` meta.
3. **Routing** — `is_design_mode` is `True` for Sat/Sun and `False` for
   weekdays, so the dark build is selected exactly on the weekend.

## Out of scope

Content, layout, copy, emoji, feed selection, and routing logic. This change
touches colour values and the `palette` plumbing only.
