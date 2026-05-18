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
    monkeypatch.setattr(newsletter, "fetch_all_feeds", lambda feeds: fake_items)
    monkeypatch.setattr(newsletter, "deduplicate", lambda items: items)
    monkeypatch.setattr(newsletter, "send_email", lambda html, subject: None)
    # Without these stubs the smoke test clobbers the real comparison log for
    # today's date (write_comparison_log writes to comparison/<today>.json on disk).
    monkeypatch.setattr(newsletter, "write_comparison_log", lambda log, base_dir: None)
    monkeypatch.setattr(newsletter, "summarize_week", lambda *a, **kw: {"week_start": "", "week_end": "", "days": []})
    newsletter.main()
