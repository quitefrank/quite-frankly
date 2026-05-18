"""Static configuration for the Quite Frankly newsletter."""

import os

RECIPIENT = "suarez.milan@gmail.com"
SENDER = "frank@quitefrank.co"
SEEN_LINKS_FILE = "seen_links.json"
SEVEN_DAYS_S = 7 * 24 * 60 * 60
TEST_MODE = os.environ.get("MODE") == "test"

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

FEEDS_WEEKDAY = [
    # Canada & Toronto
    {"url": "https://www.cbc.ca/cmlink/rss-canada-toronto",                                               "source": "CBC"},
    {"url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/canada/toronto/",             "source": "Globe & Mail"},
    {"url": "https://www.reddit.com/r/toronto/top.rss?t=day",                                            "source": "r/toronto"},
    {"url": "https://www.blogto.com/rss/articles.xml",                                                   "source": "BlogTO"},
    {"url": "https://www.thestar.com/feeds/rss/news.xml",                                                "source": "Toronto Star"},
    {"url": "https://nationalpost.com/feed",                                                             "source": "National Post"},
    {"url": "https://www.nationalnewswatch.com/feed/",                                                   "source": "National Newswatch"},
    {"url": "https://www.canadaland.com/feed/",                                                          "source": "Canadaland"},

    # Toronto Housing
    {"url": "https://globeandmail.com/arc/outboundfeeds/rss/category/investing/",                        "source": "Globe & Mail Finance"},
    {"url": "https://www.reddit.com/r/canadahousing/top.rss?t=day",                                      "source": "r/canadahousing"},
    {"url": "https://storeys.com/feed/",                                                                 "source": "Storeys"},
    {"url": "https://betterdwelling.com/feed/",                                                          "source": "BetterDwelling"},
    {"url": "https://www.moneysense.ca/category/columns/real-estate/feed/",                              "source": "MoneySense Real Estate"},

    # Tech & AI
    {"url": "https://feeds.feedburner.com/TechCrunch",                                                   "source": "TechCrunch"},
    {"url": "https://hnrss.org/frontpage",                                                               "source": "Hacker News"},
    {"url": "https://simonwillison.net/atom/everything/",                                                "source": "Simon Willison"},
    {"url": "https://stratechery.com/feed/",                                                             "source": "Stratechery"},

    # Finance & Markets
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US",  "source": "Yahoo Finance"},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                                               "source": "WSJ"},
    {"url": "https://www.moneysense.ca/feed/",                                                           "source": "MoneySense"},

    # US & Global
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                               "source": "BBC"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",                                 "source": "NYT"},
    {"url": "https://www.economist.com/international/rss.xml",                                           "source": "Economist"},
    {"url": "https://feeds.npr.org/1004/rss.xml",                                                        "source": "NPR World"},
    {"url": "https://api.axios.com/feed/",                                                               "source": "Axios"},

    # Podcasts (cultural currency, route to Worth Knowing)
    {"url": "https://rss.art19.com/the-daily",                                                           "source": "NYT The Daily"},
    {"url": "https://feeds.megaphone.fm/todayexplained",                                                 "source": "Today Explained"},
    {"url": "https://www.cbc.ca/podcasting/includes/frontburner.xml",                                    "source": "CBC Frontburner"},
    {"url": "https://podcastfeeds.nbcnews.com/HL4TzgYC",                                                 "source": "NBC Meet the Press"},
]

FEEDS_SATURDAY_STRATEGIC = [
    {"url": "https://uxdesign.cc/feed",                  "source": "UX Collective"},
    {"url": "https://www.smashingmagazine.com/feed/",    "source": "Smashing Magazine"},
    {"url": "https://www.nngroup.com/feed/rss/",         "source": "NN/g"},
    {"url": "https://www.lennysnewsletter.com/feed",     "source": "Lenny's Newsletter"},
]

FEEDS_SUNDAY_VISUAL = [
    {"url": "https://design-milk.com/feed",              "source": "Design Milk"},
    {"url": "https://hypebeast.com/feed",                "source": "Hypebeast"},
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
    "Hypebeast":   "Design & Product",
    "Codrops":     "Design & Product",
    "Sidebar":     "Design & Product",
    "Trendland":   "Design & Product",

    # Worth Knowing (podcasts)
    "NYT The Daily":      "Worth Knowing",
    "Today Explained":    "Worth Knowing",
    "CBC Frontburner":    "Worth Knowing",
    "NBC Meet the Press": "Worth Knowing",
}

SECTION_EMOJIS = {
    "Canada & Toronto": "🇨🇦",
    "Toronto Housing":  "🏠",
    "Tech & AI":        "💻",
    "Design & Product": "🎨",
    "Finance & Markets":"📈",
    "US & Global":      "🌍",
    "Worth Knowing":    "🎧",
    "Everything Else":  "📋",
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
    "Hypebeast":   "https://www.google.com/s2/favicons?domain=hypebeast.com&sz=64",
    "Codrops":     "https://www.google.com/s2/favicons?domain=tympanus.net&sz=64",
    "Sidebar":     "https://www.google.com/s2/favicons?domain=sidebar.io&sz=64",
    "Trendland":   "https://www.google.com/s2/favicons?domain=trendland.com&sz=64",

    # Worth Knowing (podcasts)
    "NYT The Daily":      "https://www.google.com/s2/favicons?domain=nytimes.com&sz=64",
    "Today Explained":    "https://www.google.com/s2/favicons?domain=vox.com&sz=64",
    "CBC Frontburner":    "https://www.google.com/s2/favicons?domain=cbc.ca&sz=64",
    "NBC Meet the Press": "https://www.google.com/s2/favicons?domain=nbcnews.com&sz=64",
}
