"""Tests for the Reddit + Hacker News traction fetchers."""

import requests_mock

from traction import fetch_reddit_traction, fetch_hn_traction


def test_fetch_reddit_traction_aggregates_across_subreddits():
    url = "https://example.com/article-1"
    with requests_mock.Mocker() as m:
        m.get(
            "https://www.reddit.com/r/news/search.json",
            json={"data": {"children": [
                {"data": {"score": 1200, "num_comments": 340, "permalink": "/r/news/x"}},
            ]}},
        )
        m.get(
            "https://www.reddit.com/r/canada/search.json",
            json={"data": {"children": []}},
        )
        result = fetch_reddit_traction(url, subreddits=["news", "canada"])
        assert result["score"] == 1200
        assert result["comments"] == 340
        assert result["subreddit_hits"] == 1


def test_fetch_reddit_traction_sums_multiple_hits():
    url = "https://example.com/article-2"
    with requests_mock.Mocker() as m:
        m.get(
            "https://www.reddit.com/r/toronto/search.json",
            json={"data": {"children": [
                {"data": {"score": 400, "num_comments": 80}},
                {"data": {"score": 100, "num_comments": 20}},
            ]}},
        )
        result = fetch_reddit_traction(url, subreddits=["toronto"])
        assert result["score"] == 500
        assert result["comments"] == 100
        assert result["subreddit_hits"] == 2


def test_fetch_reddit_traction_returns_zero_on_failure():
    url = "https://example.com/article-3"
    with requests_mock.Mocker() as m:
        m.get(requests_mock.ANY, status_code=503)
        result = fetch_reddit_traction(url, subreddits=["news"])
        assert result == {"score": 0, "comments": 0, "subreddit_hits": 0}


def test_fetch_hn_traction_returns_points_and_comments():
    url = "https://example.com/article-4"
    with requests_mock.Mocker() as m:
        m.get(
            "https://hn.algolia.com/api/v1/search",
            json={"hits": [{"points": 250, "num_comments": 120}]},
        )
        result = fetch_hn_traction(url)
        assert result["points"] == 250
        assert result["comments"] == 120


def test_fetch_hn_traction_picks_top_scoring_hit():
    url = "https://example.com/article-5"
    with requests_mock.Mocker() as m:
        m.get(
            "https://hn.algolia.com/api/v1/search",
            json={"hits": [
                {"points": 50, "num_comments": 10},
                {"points": 900, "num_comments": 400},
                {"points": 200, "num_comments": 80},
            ]},
        )
        result = fetch_hn_traction(url)
        assert result["points"] == 900
        assert result["comments"] == 400


def test_fetch_hn_traction_returns_zero_on_failure():
    url = "https://example.com/article-6"
    with requests_mock.Mocker() as m:
        m.get(requests_mock.ANY, status_code=503)
        result = fetch_hn_traction(url)
        assert result == {"points": 0, "comments": 0}


def test_fetch_hn_traction_returns_zero_on_empty_hits():
    url = "https://example.com/article-7"
    with requests_mock.Mocker() as m:
        m.get(
            "https://hn.algolia.com/api/v1/search",
            json={"hits": []},
        )
        result = fetch_hn_traction(url)
        assert result == {"points": 0, "comments": 0}
