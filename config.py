"""Static configuration for the Quite Frankly newsletter."""

RECIPIENT = "suarez.milan@gmail.com"
SENDER = "frank@quitefrank.co"
SEEN_LINKS_FILE = "seen_links.json"
SEVEN_DAYS_S = 7 * 24 * 60 * 60

FEEDS = [
    {"url": "https://www.cbc.ca/cmlink/rss-canada-toronto",                                               "source": "CBC"},
    {"url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/canada/toronto/",             "source": "Globe & Mail"},
    {"url": "https://feeds.feedburner.com/TechCrunch",                                                    "source": "TechCrunch"},
    {"url": "https://uxdesign.cc/feed",                                                                   "source": "UX Collective"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                               "source": "BBC"},
    {"url": "https://www.smashingmagazine.com/feed/",                                                     "source": "Smashing Magazine"},
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US", "source": "Yahoo Finance"},
    {"url": "https://globeandmail.com/arc/outboundfeeds/rss/category/investing/",                         "source": "Globe & Mail Finance"},
    {"url": "https://www.reddit.com/r/toronto/top.rss?t=day",                                            "source": "r/toronto"},
    {"url": "https://www.reddit.com/r/canadahousing/top.rss?t=day",                                      "source": "r/canadahousing"},
]

SECTION_MAP = {
    "CBC":                 "Canada & Toronto",
    "Globe & Mail":        "Toronto Housing",
    "TechCrunch":          "Tech & AI",
    "UX Collective":       "Design & Product",
    "Smashing Magazine":   "Design & Product",
    "BBC":                 "US & Global",
    "Yahoo Finance":       "Finance & Markets",
    "Globe & Mail Finance":"Finance & Markets",
    "r/toronto":           "Canada & Toronto",
    "r/canadahousing":     "Toronto Housing",
}

SECTION_EMOJIS = {
    "Canada & Toronto": "🇨🇦",
    "Toronto Housing":  "🏠",
    "Tech & AI":        "💻",
    "Design & Product": "🎨",
    "Finance & Markets":"📈",
    "US & Global":      "🌍",
    "Everything Else":  "📋",
}

SOURCE_FAVICONS = {
    "CBC":                 "https://www.google.com/s2/favicons?domain=cbc.ca&sz=64",
    "Globe & Mail":        "https://www.google.com/s2/favicons?domain=theglobeandmail.com&sz=64",
    "TechCrunch":          "https://www.google.com/s2/favicons?domain=techcrunch.com&sz=64",
    "UX Collective":       "https://www.google.com/s2/favicons?domain=uxdesign.cc&sz=64",
    "Smashing Magazine":   "https://www.google.com/s2/favicons?domain=smashingmagazine.com&sz=64",
    "BBC":                 "https://www.google.com/s2/favicons?domain=bbc.com&sz=64",
    "Yahoo Finance":       "https://www.google.com/s2/favicons?domain=finance.yahoo.com&sz=64",
    "Globe & Mail Finance":"https://www.google.com/s2/favicons?domain=theglobeandmail.com&sz=64",
    "r/toronto":           "https://www.google.com/s2/favicons?domain=reddit.com&sz=64",
    "r/canadahousing":     "https://www.google.com/s2/favicons?domain=reddit.com&sz=64",
}
