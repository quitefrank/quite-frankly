# Everything Else: per-item emoji + bold link prefix

**Date:** 2026-05-23
**Scope:** Visual restyle of the Everything Else section. No content changes. No new LLM calls.

## Goal

Each item in the Everything Else section gets a per-article emoji prefix and a bolded version of the existing first-words link, replacing the bulleted list. Item text, link target, ranking, and the 7-item cap stay identical to today.

## Out of scope

- The Today in the World section. Untouched.
- Any change to the main Claude call, the triage call, or any prompt.
- Any change to ranking, item selection, or `MAX_EVERYTHING_ELSE`.
- Any rewriting of headlines or per-item summaries.

## Change 1 — Restructure Everything Else item HTML

Edit `build_everything_else` in `formatting.py` (currently lines 837-894).

- Drop the `<ul>/<li>` container.
- Render each item as a `<p>` that mirrors the styling family used by Today-in-the-World items.
- Prepend each item with an emoji `<span>` (6px right margin) chosen by `pick_everything_else_emoji(title, source)`.
- Keep the existing first-4-words link behavior. Wrap the linked words in `<strong>`. Link styling otherwise unchanged (dark `#333` text, blue `#1c7ff2` underline).
- Card container, the "📋 Everything Else" section header, item ordering, item ranking logic, ID stamping, and the 7-item cap all stay as-is.

Resulting per-item HTML:

```html
<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:#333;font-family:Helvetica,Arial,sans-serif">
  <span style="margin-right:6px">🤖</span>
  <a href="..." style="color:#333;font-weight:700;text-decoration:underline;text-decoration-color:#1c7ff2;"><strong>First four words</strong></a> remaining text
</p>
```

`pick_everything_else_emoji` always returns a string (see Change 2 for the resolution order and the `📰` safety net), so the `<span>` is always present. `font-weight:700` on the `<a>` is a belt-and-suspenders pairing with the inner `<strong>` for email clients that strip semantic tags.

## Change 2 — Emoji selection helper

Add two new constants to `config.py` and one new helper to `formatting.py`.

### Resolution order

1. **Keyword regex match against the title (case-insensitive).** First match in declared order wins. Word boundaries `\b` keep matches whole-word.
2. **Source-name lookup in the source map.** Exact match on the item's `primary_source`.
3. **Final safety net:** the literal `📰` (newspaper) emoji. This only fires if a new source is added to the feed without being added to `EVERYTHING_ELSE_SOURCE_EMOJIS`. Distinct from the section header's 📋.

### Seed keyword map (`config.py`)

```python
EVERYTHING_ELSE_KEYWORD_EMOJIS = [
    # AI / tech firms
    (r"\b(openai|anthropic|gpt|claude|gemini|llm|chatgpt|copilot)\b", "🤖"),
    (r"\b(apple|iphone|ipad|mac|airpods)\b", "🍎"),
    (r"\b(google|alphabet|android|pixel)\b", "🔎"),
    (r"\b(meta|facebook|instagram|whatsapp|threads)\b", "📱"),
    (r"\b(microsoft|azure|xbox|windows)\b", "🪟"),
    (r"\b(amazon|aws|prime)\b", "📦"),
    (r"\b(tesla|musk|spacex|x corp|twitter)\b", "🚀"),

    # Housing / real estate
    (r"\b(rent|condo|landlord|mortgage|housing|real estate|listing|airbnb)\b", "🏠"),

    # Markets / finance
    (r"\b(fed|inflation|interest rate|tsx|s&p|nasdaq|dow|recession|bond|yield)\b", "📈"),
    (r"\b(crypto|bitcoin|ethereum|stablecoin)\b", "🪙"),
    (r"\b(layoff|firing|severance|hiring freeze)\b", "📉"),

    # Politics
    (r"\b(trump|biden|harris|white house|congress|senate|gop|democrat|republican)\b", "🇺🇸"),
    (r"\b(ottawa|trudeau|carney|liberal|conservative|ndp|poilievre|parliament)\b", "🇨🇦"),
    (r"\b(election|vote|ballot|poll|polling|riding)\b", "🗳️"),

    # Toronto / Ontario
    (r"\b(toronto|ontario|ttc|tdsb|leslieville|scarborough|mississauga)\b", "🏙️"),

    # World / environment
    (r"\b(climate|emissions|wildfire|hurricane|flood|heatwave)\b", "🌍"),
    (r"\b(war|ukraine|gaza|israel|hamas|nato)\b", "🕊️"),

    # Work / labour
    (r"\b(strike|union|labour|labor|walkout)\b", "👷"),

    # Culture
    (r"\b(film|movie|netflix|hollywood|streaming|series|hbo)\b", "🎬"),
    (r"\b(nba|nhl|nfl|mlb|raptors|leafs|blue jays|formula 1|world cup|olympics)\b", "🏆"),
    (r"\b(restaurant|chef|menu|michelin)\b", "🍽️"),

    # Design / product
    (r"\b(design|ux|figma|product|prototype|interaction)\b", "🎨"),
]
```

### Source map (`config.py`)

Exhaustive across every entry in `SOURCE_FAVICONS`. Each source picks an emoji that suits its beat. If a future source is added to the feed config, it should also be added here.

```python
EVERYTHING_ELSE_SOURCE_EMOJIS = {
    # Canada & Toronto
    "CBC":                "🇨🇦",
    "Globe & Mail":       "🇨🇦",
    "r/toronto":          "🏙️",
    "BlogTO":             "🏙️",
    "Toronto Star":       "🏙️",
    "National Post":      "🇨🇦",
    "National Newswatch": "🇨🇦",
    "Canadaland":         "🇨🇦",

    # Toronto Housing
    "Globe & Mail Finance":   "🏠",
    "r/canadahousing":        "🏠",
    "Storeys":                "🏠",
    "BetterDwelling":         "🏠",
    "MoneySense Real Estate": "🏠",

    # Tech & AI
    "TechCrunch":     "💻",
    "Hacker News":    "💻",
    "Simon Willison": "🤖",
    "Stratechery":    "💻",

    # Finance & Markets
    "Yahoo Finance": "📈",
    "WSJ":           "📈",
    "MoneySense":    "💰",

    # US & Global
    "BBC":       "🌍",
    "NYT":       "🇺🇸",
    "Economist": "🌍",
    "NPR World": "🌍",
    "Axios":     "🇺🇸",

    # Design & Product
    "UX Collective":      "🎨",
    "Smashing Magazine":  "🎨",
    "NN/g":               "🎨",
    "Lenny's Newsletter": "📊",
    "Design Milk":        "🎨",
    "Hypebeast":          "👟",
    "Codrops":            "🎨",
    "Sidebar":            "🎨",
    "Trendland":          "🎨",

    # Today in the World (podcasts)
    "NYT The Daily":      "🎙️",
    "Today Explained":    "🎙️",
    "CBC Frontburner":    "🎙️",
    "NBC Meet the Press": "🎙️",
}
```

### Helper (`formatting.py`)

```python
import re

def pick_everything_else_emoji(title: str, source: str) -> str:
    """Pick the per-item emoji for an Everything Else entry.

    Resolution order:
      1. First case-insensitive keyword match in EVERYTHING_ELSE_KEYWORD_EMOJIS.
      2. Exact match in EVERYTHING_ELSE_SOURCE_EMOJIS.
      3. Newspaper safety net (📰) — only reached if a new source slipped
         into the feed without being added to the source map.
    """
    text = (title or "").lower()
    for pattern, emoji in EVERYTHING_ELSE_KEYWORD_EMOJIS:
        if re.search(pattern, text):
            return emoji
    if source in EVERYTHING_ELSE_SOURCE_EMOJIS:
        return EVERYTHING_ELSE_SOURCE_EMOJIS[source]
    return "📰"
```

The renderer calls this with `(link["title"], link["source"])` and inlines the result into the per-item `<span>`.

## Tests

In `tests/`:

1. **Update existing Everything Else HTML assertions.** Any test that checks for `<ul>` or `<li>` in the Everything Else block needs to update to assert `<p>`, `<span>` with the chosen emoji, and `<strong>` around the linked words.
2. **Add `test_pick_everything_else_emoji`:**
   - Keyword match wins over source (e.g. `"OpenAI raises..."` from `"WSJ"` → 🤖, not 📈).
   - Source fallback when no keyword matches (e.g. `"Quiet Monday at the market"` from `"WSJ"` → 📈).
   - Safety net `📰` when neither matches (e.g. title and source both unmapped).
   - Case-insensitive (`"OPENAI"`, `"OpenAI"`, `"openai"` all match).
   - Word boundary protection (`"capitalism"` should not match the `"apple"` rule, etc.).

## Files touched

| File | Change |
| --- | --- |
| `config.py` | Add `EVERYTHING_ELSE_KEYWORD_EMOJIS`, `EVERYTHING_ELSE_SOURCE_EMOJIS`. |
| `formatting.py` | Rewrite `build_everything_else` HTML; add `pick_everything_else_emoji`. |
| `tests/` | Update Everything Else HTML assertions; add helper unit tests. |

## Non-changes (explicit)

- `_render_today_in_the_world` — unchanged.
- `FORMAT_SYSTEM_PROMPT` and `LEGACY_FORMAT_SYSTEM_PROMPT` — unchanged.
- `MAX_EVERYTHING_ELSE` — unchanged (7).
- The card container, padding, border-radius, and "📋 Everything Else" section header — unchanged.
- The section emoji map `SECTION_EMOJIS` — unchanged.

## Open items for future passes

- The seed keyword map will need tuning as Frank reads the newsletter. Refine by reviewing actual Everything Else items each week and adding patterns for repeated misses.
- If multiple items in the same Everything Else block end up with the same emoji on a regular basis, consider tightening the keyword map or de-duplicating per-day.
