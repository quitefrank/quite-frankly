def test_smoke_pytest_runs():
    assert True


def test_main_runs_through_two_passes(fake_anthropic_client, monkeypatch):
    fake_items = [
        {"title": "Toronto council debates housing supply", "link": "https://example.com/1", "snippet": "", "image": "", "source": "CBC"},
        {"title": "Bank of Canada holds rates steady", "link": "https://example.com/2", "snippet": "", "image": "", "source": "Yahoo Finance"},
    ]

    monkeypatch.setattr("formatting.send_email", lambda html, subject: None)
    monkeypatch.setattr("pipeline.fetch_all_feeds", lambda feeds: fake_items)
    monkeypatch.setattr("pipeline.deduplicate", lambda items: items)

    # Patch the imports newsletter.py has already done at module load time.
    import newsletter
    import triage
    monkeypatch.setattr(newsletter, "fetch_all_feeds", lambda feeds: fake_items)
    monkeypatch.setattr(newsletter, "deduplicate", lambda items: items)
    monkeypatch.setattr(newsletter, "send_email", lambda html, subject: None)
    # Keep the smoke test offline: stub the live Reddit/HN calls that the
    # new Phase 2 path runs between triage and format.
    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 0, "comments": 0, "subreddit_hits": 0})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0, "comments": 0})
    newsletter.main()
