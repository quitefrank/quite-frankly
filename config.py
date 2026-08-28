"""Static configuration for the Quite Frankly newsletter."""

import os
from pathlib import Path

RECIPIENT = "suarez.milan@gmail.com"
SENDER = "frank@quitefrank.co"
SEEN_LINKS_FILE = "seen_links.json"
SEVEN_DAYS_S = 7 * 24 * 60 * 60
TEST_MODE = os.environ.get("MODE") == "test"

# --- Parked sections ---
# Tech & AI parked 2026-07-17: Frank gets more comprehensive tech/AI coverage
# from another newsletter. Everything below (feeds, SECTION_MAP rows, favicons,
# emoji, prompt scaffolding) is left in place, inert. To restore the section,
# flip this to True. No other change is required.
TECH_AI_ENABLED = False

# "What this means" callout mode. "section" renders one per-section block
# collecting every relevant item (featured or Other Headlines); "article"
# restores the legacy one-line-per-featured-story callout. Flip the default
# (or set CALLOUT_MODE=article in the workflow env) to revert with no loss.
CALLOUT_MODE = os.environ.get("CALLOUT_MODE", "section")

# Drop feed items whose RSS summary is shorter than this. Hub/index feeds
# (e.g., the Economist's "the-world-this-week") publish entries with empty
# descriptions; without a snippet, the formatter has nothing to write a body
# from and emits headline+source with no story text.
MIN_SNIPPET_CHARS = 20

REDDIT_SUBREDDITS = [
    "news",
    "worldnews",
    "canada",
    "toronto",
    "canadahousing",
    "technology",
    "OntarioHousing",
]

# Searched instead of REDDIT_SUBREDDITS on weekend design editions so the
# reddit "most talked about" signal reflects design/product discussion, not
# news. Kept to ~6 subs to stay under Reddit's anonymous ~60 req/min ceiling
# (6 subreddit searches + 1 HN call per item, 5 concurrent workers).
DESIGN_SUBREDDITS = [
    "userexperience",
    "UXDesign",
    "web_design",
    "graphic_design",
    "ProductManagement",
    "Design",
]

_TECH_AI_FEEDS = [
    {"url": "https://feeds.feedburner.com/TechCrunch",                                                   "source": "TechCrunch"},
    {"url": "https://hnrss.org/frontpage",                                                               "source": "Hacker News"},
    {"url": "https://simonwillison.net/atom/everything/",                                                "source": "Simon Willison"},
    {"url": "https://stratechery.com/feed/",                                                             "source": "Stratechery"},
]

_WEEKDAY_FEEDS_CANADA_TORONTO = [
    {"url": "https://www.cbc.ca/cmlink/rss-canada-toronto",                                               "source": "CBC"},
    {"url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/canada/toronto/",             "source": "Globe & Mail"},
    {"url": "https://www.reddit.com/r/toronto/top.rss?t=day",                                            "source": "r/toronto"},
    {"url": "https://www.blogto.com/rss/articles.xml",                                                   "source": "BlogTO"},
    {"url": "https://www.thestar.com/feeds/rss/news.xml",                                                "source": "Toronto Star"},
    {"url": "https://nationalpost.com/feed",                                                             "source": "National Post"},
    {"url": "https://www.nationalnewswatch.com/feed/",                                                   "source": "National Newswatch"},
    {"url": "https://www.canadaland.com/feed/",                                                          "source": "Canadaland"},
]

_WEEKDAY_FEEDS_HOUSING = [
    {"url": "https://globeandmail.com/arc/outboundfeeds/rss/category/investing/",                        "source": "Globe & Mail Finance"},
    {"url": "https://www.reddit.com/r/canadahousing/top.rss?t=day",                                      "source": "r/canadahousing"},
    {"url": "https://storeys.com/feed/",                                                                 "source": "Storeys"},
    {"url": "https://betterdwelling.com/feed/",                                                          "source": "BetterDwelling"},
    {"url": "https://www.moneysense.ca/category/columns/real-estate/feed/",                              "source": "MoneySense Real Estate"},
]

_WEEKDAY_FEEDS_FINANCE = [
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US",  "source": "Yahoo Finance"},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                                               "source": "WSJ"},
    {"url": "https://www.moneysense.ca/feed/",                                                           "source": "MoneySense"},
]

_WEEKDAY_FEEDS_US_GLOBAL = [
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                               "source": "BBC"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",                                 "source": "NYT"},
    {"url": "https://www.economist.com/international/rss.xml",                                           "source": "Economist"},
    {"url": "https://feeds.npr.org/1004/rss.xml",                                                        "source": "NPR World"},
    {"url": "https://api.axios.com/feed/",                                                               "source": "Axios"},
]

_WEEKDAY_FEEDS_PODCASTS = [
    {"url": "https://rss.art19.com/the-daily",                                                           "source": "NYT The Daily"},
    {"url": "https://feeds.megaphone.fm/VMP5705694065",                                                  "source": "Today Explained"},
    {"url": "https://www.cbc.ca/podcasting/includes/frontburner.xml",                                    "source": "CBC Frontburner"},
    {"url": "https://podcastfeeds.nbcnews.com/HL4TzgYC",                                                 "source": "NBC Meet the Press"},
]


def _weekday_feeds(tech_enabled: bool) -> list[dict]:
    """Compose the weekday feed set. Tech & AI is included only when enabled;
    it is parked by default (see TECH_AI_ENABLED). Keeping _TECH_AI_FEEDS
    defined and splicing it here makes re-enabling a one-flag change."""
    feeds = []
    feeds += _WEEKDAY_FEEDS_CANADA_TORONTO
    feeds += _WEEKDAY_FEEDS_HOUSING
    if tech_enabled:
        feeds += _TECH_AI_FEEDS
    feeds += _WEEKDAY_FEEDS_FINANCE
    feeds += _WEEKDAY_FEEDS_US_GLOBAL
    feeds += _WEEKDAY_FEEDS_PODCASTS
    return feeds


FEEDS_WEEKDAY = _weekday_feeds(TECH_AI_ENABLED)

FEEDS_SATURDAY_STRATEGIC = [
    {"url": "https://uxdesign.cc/feed",                  "source": "UX Collective"},
    {"url": "https://www.smashingmagazine.com/feed/",    "source": "Smashing Magazine"},
    {"url": "https://www.nngroup.com/feed/rss/",         "source": "NN/g"},
    {"url": "https://www.lennysnewsletter.com/feed",     "source": "Lenny's Newsletter"},
]

FEEDS_SUNDAY_VISUAL = [
    {"url": "https://design-milk.com/feed",              "source": "Design Milk"},
    {"url": "https://www.itsnicethat.com/articles.rss",  "source": "It's Nice That"},
    {"url": "https://tympanus.net/codrops/feed/",        "source": "Codrops"},
    {"url": "https://sidebar.io/feed.xml",               "source": "Sidebar"},
    {"url": "https://trendland.com/feed/",               "source": "Trendland"},
]

FEEDS = FEEDS_WEEKDAY  # back-compat alias, removed in Task 6

SECTION_MAP = {
    # Canada & Toronto
    "CBC":                 "Canada & Toronto",
    "Globe & Mail":        "Canada & Toronto",
    "r/toronto":           "Canada & Toronto",
    "BlogTO":              "Canada & Toronto",
    "Toronto Star":        "Canada & Toronto",
    "National Post":       "Canada & Toronto",
    "National Newswatch":  "Canada & Toronto",
    "Canadaland":          "Canada & Toronto",

    # Toronto Housing
    "Globe & Mail Finance":   "Toronto Housing",
    "r/canadahousing":        "Toronto Housing",
    "Storeys":                "Toronto Housing",
    "BetterDwelling":         "Toronto Housing",
    "MoneySense Real Estate": "Toronto Housing",

    # Tech & AI
    "TechCrunch":      "Tech & AI",
    "Hacker News":     "Tech & AI",
    "Simon Willison":  "Tech & AI",
    "Stratechery":     "Tech & AI",

    # Finance & Markets
    "Yahoo Finance":   "Finance & Markets",
    "WSJ":             "Finance & Markets",
    "MoneySense":      "Finance & Markets",

    # US & Global
    "BBC":         "US & Global",
    "NYT":         "US & Global",
    "Economist":   "US & Global",
    "NPR World":   "US & Global",
    "Axios":       "US & Global",

    # Design & Product (Saturday strategic + carryover weekday)
    "UX Collective":      "Design & Product",
    "Smashing Magazine":  "Design & Product",
    "NN/g":               "Design & Product",
    "Lenny's Newsletter": "Design & Product",

    # Design & Product (Sunday visual)
    "Design Milk": "Design & Product",
    "It's Nice That":  "Design & Product",
    "Codrops":     "Design & Product",
    "Sidebar":     "Design & Product",
    "Trendland":   "Design & Product",

    # Today in the World (podcasts)
    "NYT The Daily":      "Today in the World",
    "Today Explained":    "Today in the World",
    "CBC Frontburner":    "Today in the World",
    "NBC Meet the Press": "Today in the World",
}

# Sources whose RSS "link" points to a podcast/audio resource rather than an
# article page. og:image fetches against these always 404 — skip the HTTP
# call to keep CI logs clean.
#
# This set does double duty: fetch_feed also reads it to decide which feeds may
# fall back to the channel's own artwork, because that fallback is only
# defensible where og:image enrichment will never run. Adding a source here
# therefore hands its items the publisher's masthead as their image. Do not add
# a source just to silence noisy og fetches — WSJ (401) and The Economist (403)
# are tempting and would both break, since their channel artwork is a dead URL.
# Silencing log noise wants a separate constant.
SOURCES_SKIP_OG_IMAGE = {
    "CBC Frontburner",
    "NYT The Daily",
    "Today Explained",
    "NBC Meet the Press",
}

SECTION_EMOJIS = {
    "Canada & Toronto": "🇨🇦",
    "Toronto Housing":  "🏠",
    "Tech & AI":        "💻",
    "Design & Product": "🎨",
    "Finance & Markets":"📈",
    "US & Global":      "🌍",
    "Today in the World": "🌐",
    "Everything Else":  "📋",
}

# Per-item emoji selection for Everything Else.
# Rule: every emoji within an Everything Else section is unique.
# Resolution order in formatting.pick_everything_else_emoji (first
# candidate not already used in the section wins):
#   1. Case-insensitive keyword regex matches (declared order).
#   2. Exact source-name lookup in EVERYTHING_ELSE_SOURCE_EMOJIS.
#   3. EVERYTHING_ELSE_FALLBACK_POOL, in order.
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

# Neutral fallbacks for Everything Else dedup: when both the keyword pick
# and the source pick are already used in the section, walk this pool in
# order to find an unused emoji. Topic-agnostic on purpose — by the time
# we reach here, the topical signal is gone anyway.
EVERYTHING_ELSE_FALLBACK_POOL = ["📰", "📌", "🔖", "📎", "✨", "🧭", "📝"]

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
    "It's Nice That":     "🎨",
    "Codrops":            "🎨",
    "Sidebar":            "🎨",
    "Trendland":          "🎨",

    # Today in the World (podcasts)
    "NYT The Daily":      "🎙️",
    "Today Explained":    "🎙️",
    "CBC Frontburner":    "🎙️",
    "NBC Meet the Press": "🎙️",
}

SOURCE_FAVICONS = {
    # Canada & Toronto
    "CBC":                "https://www.google.com/s2/favicons?domain=cbc.ca&sz=64",
    "Globe & Mail":       "https://www.google.com/s2/favicons?domain=theglobeandmail.com&sz=64",
    "r/toronto":          "https://www.google.com/s2/favicons?domain=reddit.com&sz=64",
    "BlogTO":             "https://www.google.com/s2/favicons?domain=blogto.com&sz=64",
    "Toronto Star":       "https://www.google.com/s2/favicons?domain=thestar.com&sz=64",
    "National Post":      "https://www.google.com/s2/favicons?domain=nationalpost.com&sz=64",
    "National Newswatch": "https://www.google.com/s2/favicons?domain=nationalnewswatch.com&sz=64",
    "Canadaland":         "https://www.google.com/s2/favicons?domain=canadaland.com&sz=64",

    # Toronto Housing
    "Globe & Mail Finance":   "https://www.google.com/s2/favicons?domain=theglobeandmail.com&sz=64",
    "r/canadahousing":        "https://www.google.com/s2/favicons?domain=reddit.com&sz=64",
    "Storeys":                "https://www.google.com/s2/favicons?domain=storeys.com&sz=64",
    "BetterDwelling":         "https://www.google.com/s2/favicons?domain=betterdwelling.com&sz=64",
    "MoneySense Real Estate": "https://www.google.com/s2/favicons?domain=moneysense.ca&sz=64",

    # Tech & AI
    "TechCrunch":     "https://www.google.com/s2/favicons?domain=techcrunch.com&sz=64",
    "Hacker News":    "https://www.google.com/s2/favicons?domain=news.ycombinator.com&sz=64",
    "Simon Willison": "https://www.google.com/s2/favicons?domain=simonwillison.net&sz=64",
    "Stratechery":    "https://www.google.com/s2/favicons?domain=stratechery.com&sz=64",

    # Finance & Markets
    "Yahoo Finance": "https://www.google.com/s2/favicons?domain=finance.yahoo.com&sz=64",
    "WSJ":           "https://www.google.com/s2/favicons?domain=wsj.com&sz=64",
    "MoneySense":    "https://www.google.com/s2/favicons?domain=moneysense.ca&sz=64",

    # US & Global
    "BBC":       "https://www.google.com/s2/favicons?domain=bbc.com&sz=64",
    "NYT":       "https://www.google.com/s2/favicons?domain=nytimes.com&sz=64",
    "Economist": "https://www.google.com/s2/favicons?domain=economist.com&sz=64",
    "NPR World": "https://www.google.com/s2/favicons?domain=npr.org&sz=64",
    "Axios":     "https://www.google.com/s2/favicons?domain=axios.com&sz=64",

    # Design & Product (Saturday strategic)
    "UX Collective":      "https://www.google.com/s2/favicons?domain=uxdesign.cc&sz=64",
    "Smashing Magazine":  "https://www.google.com/s2/favicons?domain=smashingmagazine.com&sz=64",
    "NN/g":               "https://www.google.com/s2/favicons?domain=nngroup.com&sz=64",
    "Lenny's Newsletter": "https://www.google.com/s2/favicons?domain=lennysnewsletter.com&sz=64",

    # Design & Product (Sunday visual)
    "Design Milk": "https://www.google.com/s2/favicons?domain=design-milk.com&sz=64",
    "It's Nice That":  "https://www.google.com/s2/favicons?domain=itsnicethat.com&sz=64",
    "Codrops":     "https://www.google.com/s2/favicons?domain=tympanus.net&sz=64",
    "Sidebar":     "https://www.google.com/s2/favicons?domain=sidebar.io&sz=64",
    "Trendland":   "https://www.google.com/s2/favicons?domain=trendland.com&sz=64",

    # Today in the World (podcasts)
    "NYT The Daily":      "https://www.google.com/s2/favicons?domain=nytimes.com&sz=64",
    "Today Explained":    "https://www.google.com/s2/favicons?domain=vox.com&sz=64",
    "CBC Frontburner":    "https://www.google.com/s2/favicons?domain=cbc.ca&sz=64",
    "NBC Meet the Press": "https://www.google.com/s2/favicons?domain=nbcnews.com&sz=64",
}

# --- Everything Else thumbnails ---
EE_THUMB_SIZE = 80                     # rendered thumbnail edge, px
EE_THUMB_RADIUS = 8                    # CSS border-radius, px
EE_THUMB_CACHE_DIR = "tmp/ee_thumb_cache"
EE_THUMB_FETCH_TIMEOUT_S = 4.0         # download an og:image
EE_THUMB_FETCH_MAX_BYTES = 5_000_000   # cap a downloaded image at 5 MB
EE_THUMB_MAX_WORKERS = 6               # concurrent resolves

# Per-source fallback tiles, replacing the Gemini image generation that used to
# sit here. Generation was billed per call, unbounded in the send path, and
# failed three separate ways in two weeks (quota 429s across four editions, an
# output safety block, and no timeout at all). A committed PNG has none of those
# failure modes. Files are named by images._tile_slug of the source name, so
# "National Post" -> national-post.png, and anything unmapped gets the default.
# Absolute, resolved against this file rather than the working directory: a
# relative path would silently yield zero tiles and drop every row to text if
# anything ever ran the newsletter from elsewhere.
EE_TILE_DIR = str(Path(__file__).resolve().parent / "assets" / "ee_tiles")
EE_TILE_DEFAULT = "_default.png"
