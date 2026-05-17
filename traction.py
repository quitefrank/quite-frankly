"""Free traction signals: Reddit JSON search and Hacker News Algolia."""

import requests


REDDIT_HEADERS = {"User-Agent": "QuiteFranklyBot/1.0"}


def fetch_reddit_traction(url: str, subreddits: list[str]) -> dict:
    total_score = 0
    total_comments = 0
    hits = 0
    for sub in subreddits:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/search.json",
                params={"q": f"url:{url}", "restrict_sr": 1, "limit": 5},
                headers=REDDIT_HEADERS,
                timeout=5,
            )
            if resp.status_code != 200:
                continue
            children = resp.json().get("data", {}).get("children", [])
            for c in children:
                d = c.get("data", {})
                total_score += d.get("score", 0)
                total_comments += d.get("num_comments", 0)
                hits += 1
        except Exception as e:
            print(f"  Reddit error on r/{sub}: {e}")
            continue
    return {"score": total_score, "comments": total_comments, "subreddit_hits": hits}


def fetch_hn_traction(url: str) -> dict:
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": url, "tags": "story", "hitsPerPage": 5},
            timeout=5,
        )
        if resp.status_code != 200:
            return {"points": 0, "comments": 0}
        hits = resp.json().get("hits", [])
        if not hits:
            return {"points": 0, "comments": 0}
        top = max(hits, key=lambda h: h.get("points", 0))
        return {"points": top.get("points", 0), "comments": top.get("num_comments", 0)}
    except Exception as e:
        print(f"  HN error: {e}")
        return {"points": 0, "comments": 0}
